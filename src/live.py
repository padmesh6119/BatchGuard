"""Durable live intake, actual queue inference and host execution receipts.

Demo and submitted streams are isolated. A submitted scan is an unverified
observation, never an adjudicated pack outcome or a training label.
"""
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
import platform
import hashlib
import time
import uuid

import numpy as np

from src import layer_a
from src.common import DATA_PROCESSED, ROOT, digest, environment, file_hash
from src.fusion import decision_context, load_models, rank_candidates
from src.planning import plan_candidates
from src.demo_input import DEMO_CSV, parse_demo_csv
from src.simulator import CITIES, ScanEvent, candidate_id

WINDOW = 6 * 3600
LIMIT = 10000


class LiveEngine:
    def __init__(self, store, df=None, models=None, now=time.time):
        self.store, self.now = store, now
        self.lock = RLock()
        self.df = layer_a.load_dataset() if df is None else df
        if df is None:
            self.df = self.df.merge(layer_a.load_provenance()[["build_record_id", "source_sheet", "source_excel_rows_json"]],
                                    on="build_record_id", validate="one_to_one")
        self.models = ({b: model for b in ("sklearn", "snapml") if (model := load_models(b)) is not None}
                       if models is None else models)
        self.contexts, self.streams = {}, {"demo": {}, "submitted": {}}
        self.revisions = {"demo": 0, "submitted": 0}
        self.samples = deque(maxlen=1000)
        self.started = time.monotonic()
        self.accepted = 0
        self.store.verify()
        for record in self.store.export()["events"]:
            if record["kind"] == "live_reset":
                stream = record["payload"]["stream"]
                self.streams[stream].clear()
                self.revisions[stream] = record["sequence"]
            elif record["kind"] == "live_scan":
                payload = record["payload"]
                stream = payload["stream"]
                event = ScanEvent.parse(payload["event"])
                self.streams[stream][event.event_id] = payload
                self.revisions[stream] = record["sequence"]
        self.host = environment()
        self.manifest_sha = file_hash(DATA_PROCESSED / "manifest.json")
        for stream in self.streams:
            self._evict(stream)

    def _stream(self, name):
        if name not in self.streams:
            raise ValueError("stream must be demo or submitted")
        return self.streams[name]

    def _evict(self, stream):
        cutoff = self.now() - WINDOW
        self.streams[stream] = {identity: row for identity, row in self._stream(stream).items()
                                if ScanEvent.parse(row["event"]).timestamp >= cutoff}

    def ingest(self, payload):
        event = ScanEvent.parse(payload)
        stream = "demo" if event.simulated else "submitted"
        normalized = dict(event.__dict__)
        with self.lock:
            self._evict(stream)
            events = self._stream(stream)
            identity = stream + ":" + event.event_id
            previous = self.store.latest_event("live_scan", identity)
            if previous:
                if previous["payload"]["event"] != normalized:
                    raise ValueError("Conflicting event_id in live stream")
                return {"duplicate": True, "stream": stream, "revision": self.revisions[stream]}
            now = self.now()
            if event.timestamp > now + 60:
                raise ValueError("Scan time is more than 60 seconds ahead of server receipt")
            if event.timestamp < now - WINDOW:
                raise ValueError("Live scans must fall within the current six-hour window")
            active = sum(ScanEvent.parse(row["event"]).timestamp >= now - WINDOW for row in events.values())
            if active >= LIMIT:
                raise ValueError("Live demonstration limit reached: 10000 active scans per stream")
            record = {"stream": stream, "event": normalized,
                      "received_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                      "telemetry_status": "source and scan quality unverified"}
            key = digest(["live_scan", stream, event.event_id])
            saved = self.store.append(key, "live_scan", identity, record)
            events[event.event_id] = record
            self.revisions[stream] = saved["sequence"]
            self.accepted += 1
            return {"duplicate": False, "stream": stream, "revision": saved["sequence"]}

    def reset_demo(self):
        with self.lock:
            saved = self.store.append(str(uuid.uuid4()), "live_reset", "demo", {"stream": "demo"})
            self.streams["demo"].clear()
            self.revisions["demo"] = saved["sequence"]
            return {"stream": "demo", "revision": saved["sequence"], "audit_retained": True}

    def scenario(self, name):
        if name not in {"seed", "routine", "travel", "burst"}:
            raise ValueError("scenario must be seed, routine, travel or burst")
        with self.lock:
            self._evict("demo")
            if name == "seed":
                if self.streams["demo"]:
                    return {"scenario": name, "scans_added": 0, "revision": self.revisions["demo"], "stream": "demo", "simulated": True}
                for _ in range(6):
                    self.scenario("routine")
                return {"scenario": name, "scans_added": 6, "revision": self.revisions["demo"], "stream": "demo", "simulated": True}
            eligible = self.df[self.df["manufacturer_name_normalized"].str.strip().ne("")
                               & self.df["batch_no"].str.strip().ne("")]
            if eligible.empty:
                raise ValueError("No reference batch is available for the scenario")
            # Use a stable real reference; only the observations and locations are simulated.
            eligible = eligible.sort_values(["collection_month", "build_record_id"]).drop_duplicates(
                ["product", "batch_no", "manufacturer_name_normalized"])
            existing = [row["event"] for row in self.streams["demo"].values()]
            observed = {ScanEvent.parse(event).candidate for event in existing}
            if name != "routine" and existing:
                event = existing[-1]
                ref = {"product": event["product"], "batch_no": event["batch_no"],
                       "manufacturer_name_normalized": event["manufacturer_key"]}
            else:
                available = [row for row in eligible.to_dict("records") if
                             candidate_id(row["product"], row["batch_no"], row["manufacturer_name_normalized"]) not in observed]
                ref = (available or eligible.to_dict("records"))[0]
            token, now = str(uuid.uuid4()), self.now()
            count = 12 if name == "burst" else 2 if name == "travel" else 1
            cities = [CITIES[0], next(city for city in CITIES if city[0] == "Delhi")]
            accepted = []
            for index in range(count):
                city = cities[1] if name == "travel" and index else cities[0]
                seconds_before_end = (count - index - 1) * (240 if name == "travel" else 2)
                event = {"event_id": f"LIVE-DEMO-{token}-{index}", "pack_id": f"DEMO-PACK-{token}",
                         "product": ref["product"], "batch_no": ref["batch_no"],
                         "manufacturer_key": ref["manufacturer_name_normalized"],
                         "event_time": datetime.fromtimestamp(now - seconds_before_end, timezone.utc).isoformat(),
                         "source_id": f"DEMO-READER-{index % 2}", "latitude": city[2], "longitude": city[3],
                         "simulated": True}
                accepted.append(self.ingest(event))
            return {"scenario": name, "scans_added": len(accepted), "revision": self.revisions["demo"],
                    "stream": "demo", "simulated": True}

    def run_demo(self, request_id, backend="sklearn", history_share=.75, csv_text=None):
        """Fixed scenario, actual inference and checked outcomes; never field validation."""
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 100:
            raise ValueError("Provide a demo request_id of 1–100 characters")
        if backend not in self.models:
            raise ValueError("Backend unavailable on this running host")
        csv_text = DEMO_CSV.read_text() if csv_text is None else csv_text
        input_sha = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        # Validate every row before resetting the demo or writing any scan.
        parsed = parse_demo_csv(csv_text, self.now(), str(uuid.uuid4()))
        with self.lock:
            previous = self.store.request(request_id)
            parameters = {"backend": backend, "history_share": history_share, "input_csv_sha256": input_sha}
            if previous:
                if previous["kind"] != "demo_validation" or previous["payload"]["parameters"] != parameters:
                    raise ValueError("Request ID already used for a different event")
                return {**previous["payload"], "duplicate": True}
            self.reset_demo()
            for stage, event in parsed:
                if stage == "baseline":
                    self.ingest(event)
            baseline = self.snapshot(backend=backend, capacity=4, history_share=history_share)
            conflict_events = [event for stage, event in parsed if stage == "conflict"]
            target_id = ScanEvent.parse(conflict_events[0]).candidate
            target = next(row for row in baseline["queue"] if row["candidate_id"] == target_id)
            for event in conflict_events:
                self.ingest(event)
            retry = self.ingest(next(event for stage, event in parsed if stage == "retry"))
            after = self.snapshot(backend=backend, capacity=4, history_share=history_share)
            selected = next(row for row in after["queue"] if row["candidate_id"] == target["candidate_id"])
            evidence = after["candidates"][selected["candidate_id"]]
            checks = [
                {"id": "routine_clear", "label": "12 routine batches have no scan alert", "passed": all(not r["scan_alert"] for r in baseline["queue"])},
                {"id": "travel_alert", "label": "Chennai → Delhi in 4 minutes triggers a location-conflict alert", "passed": "CLONE_PATTERN_TRAVEL_REVIEW" in selected["reason_codes"]},
                {"id": "capacity", "label": "Affected batch moves from outside capacity into the four-slot shortlist", "passed": target["rank"] > 4 and selected["rank"] <= 4},
                {"id": "retry", "label": "Retry is ignored: 14 unique scans remain", "passed": retry["duplicate"] and len(after["events"]) == 14},
                {"id": "source", "label": "Original workbook, sheet and row evidence is available", "passed": bool(evidence["reports"]) and all(r.get("source_file") and r.get("source_sheet") and r.get("source_excel_rows_json") for r in evidence["reports"])},
            ]
            # This is a labelled scripted action in the demo stream, never an inspector assertion.
            decision = {"candidate_id": selected["candidate_id"], "reviewer_id": "scripted-demo",
                        "status": "sample requested", "note": "SCRIPTED DEMONSTRATION ONLY. No real sample request or laboratory dispatch was made.",
                        "batch": selected["batch_no"], "product": selected["product"], "manufacturer": selected["manufacturer"],
                        "rank": selected["rank"], "priority": selected["priority_score"], "capacity": 4,
                        "stream": "demo", "revision": after["revision"], "strategy": "protected_history",
                        "model_version": after["model_version"], "queue_sha256": after["queue_sha256"],
                        "as_of": after["as_of"], "machine": self.host["machine"],
                        "simulated_scan_context": True, "scripted_demo": True, "fixture_id": "DEMO-TRAVEL-001"}
            prerequisites_passed = all(check["passed"] for check in checks)
            saved = None
            if prerequisites_passed:
                self.store.append("demo-decision:" + request_id, "live_decision", "demo:" + selected["candidate_id"], decision)
                saved = self.store.latest_event("live_decision", "demo:" + selected["candidate_id"])
            checks.append({"id": "decision", "label": "Labelled demo decision persisted after prerequisite checks", "passed": bool(saved and saved["payload"] == decision)})
            audit = self.store.verify()
            checks.append({"id": "audit", "label": "Audit hash chain verifies", "passed": audit["valid"]})
            result = {"fixture_id": "DEMO-TRAVEL-001", "parameters": parameters,
                      "simulated": True, "scope": "Scripted integration check; not field accuracy or counterfeit proof",
                      "passed": all(check["passed"] for check in checks), "checks": checks,
                      "candidate_id": selected["candidate_id"], "before_rank": target["rank"], "after_rank": selected["rank"],
                      "capacity": 4, "input_file": "inspection_case.csv", "input_rows": len(parsed), "input_csv_sha256": input_sha,
                      "input_csv": csv_text, "baseline_queue_sha256": baseline["queue_sha256"],
                      "snapshot": after, "audit_head_before_validation": audit["head_sha256"]}
            self.store.append(request_id, "demo_validation", "DEMO-TRAVEL-001", result)
            return {**result, "duplicate": False}

    def snapshot(self, backend="sklearn", strategy="protected_history", capacity=10, stream="demo", history_share=.75):
        if type(capacity) is not int or not 1 <= capacity <= 1000:
            raise ValueError("capacity must be 1–1000")
        if strategy not in {"legacy", "protected_history"}:
            raise ValueError("Unknown queue strategy")
        if backend not in self.models:
            raise ValueError("Backend unavailable on this running host")
        with self.lock:
            started, now = time.perf_counter(), self.now()
            stored = self._stream(stream)
            events = [r["event"] for r in stored.values() if now - WINDOW <= ScanEvent.parse(r["event"]).timestamp <= now]
            events.sort(key=lambda e: (e["event_time"], e["event_id"]))
            month = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
            key = (backend, month)
            cold = bool(events) and key not in self.contexts
            models = self.models[backend]
            if events and key not in self.contexts:
                self.contexts[key] = decision_context(self.df, month, models)
            ranked = rank_candidates(self.df, events, now, models, self.contexts.get(key)) if events else []
            if strategy == "protected_history":
                ranked = plan_candidates(ranked, history_share)
            elapsed = (time.perf_counter() - started) * 1000
            if events:
                self.samples.append(elapsed)
            candidates = self.evidence(ranked, month)
            cities = {(lat, lon): (name, state) for name, state, lat, lon in CITIES}
            feed = []
            for payload in events:
                event = ScanEvent.parse(payload)
                city, state = cities.get((event.latitude, event.longitude),
                                         (f"{event.latitude:.3f}, {event.longitude:.3f}", "Location unverified"))
                feed.append({"id": event.event_id, "pack": event.pack_id, "time": event.event_time,
                             "source": event.source_id, "lat": event.latitude, "lon": event.longitude,
                             "city": city, "state": state, "cand": event.candidate, "simulated": event.simulated})
            return {"revision": self.revisions[stream], "stream": stream, "queue": ranked,
                    "events": feed, "candidates": candidates, "decision_month": month,
                    "as_of": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                    "backend": backend, "model_version": models.version, "capacity": capacity,
                    "strategy": strategy, "history_share": history_share,
                    "history_universe": len(self.contexts.get(key, {}).get("history", [])),
                    "queue_compute_ms": elapsed, "includes_cold_context": cold,
                    "quality_status": "unverified incoming observations; no adjudicated field accuracy claim",
                    "queue_sha256": digest([[r["candidate_id"], r["rank"], r["priority_score"], r["scan_anomaly"]] for r in ranked])}

    def evidence(self, ranked, month):
        from app.dashboard import rows
        past = self.df[self.df["collection_month"].lt(month)]
        names = past["manufacturer_name_normalized"].str.strip().str.casefold()
        products = past["product"].str.strip().str.casefold()
        result = {}
        for candidate in ranked:
            manufacturer = candidate["manufacturer"].strip().casefold()
            related = past[products.eq(candidate["product"].strip().casefold()) & names.ne(manufacturer)
                           & past["source_category"].isin(layer_a.NSQ)]
            result[candidate["candidate_id"]] = {
                "product": candidate["product"], "batch": candidate["batch_no"], "manufacturer": candidate["manufacturer"],
                "history": rows(past[names.eq(manufacturer)].sort_values("collection_month", ascending=False)),
                "reports": rows(past[past["build_record_id"].isin(candidate["historical_record_ids"])]),
                "product_context": {"total": len(related), "records": rows(related.sort_values("collection_month", ascending=False).head(12))}}
        return result

    def receipt(self):
        with self.lock:
            values = np.asarray(self.samples, dtype=float)
            return {"purpose": "execution receipt from the running service; not independent hardware attestation",
                    "created_at": datetime.fromtimestamp(self.now(), timezone.utc).isoformat(),
                    "environment": self.host, "running_on_s390x": platform.machine().lower() == "s390x",
                    "uptime_seconds": time.monotonic() - self.started, "accepted_scans_this_process": self.accepted,
                    "queue_measurements": {"count": len(values),
                        "p50_ms": float(np.percentile(values, 50)) if len(values) else None,
                        "p95_ms": float(np.percentile(values, 95)) if len(values) else None,
                        "scope": "ranking and cold monthly context when needed; excludes HTTP and evidence serialization"},
                    "processed_manifest_sha256": self.manifest_sha,
                    "models": {b: model.version for b, model in self.models.items()},
                    "model_artifact_sha256": {b: model.card["artifacts"] for b, model in self.models.items()},
                    "code_sha256": {name: file_hash(ROOT / name) for name in (
                        "src/live.py", "src/demo_input.py", "src/fusion.py", "src/planning.py", "src/audit_store.py", "app/server.py")},
                    "live_code_sha256": file_hash(Path(__file__)), "audit": self.store.verify(),
                    "revisions": dict(self.revisions), "hardware_acceleration_verified": False}
