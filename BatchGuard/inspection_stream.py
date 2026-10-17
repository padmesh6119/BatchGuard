"""Persistent, local pack-scan replay. All detector outputs require human review."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3

POLICY_VERSION = "corroboration-v1"
WINDOW_SECONDS = 30 * 60
BURST_SECONDS = 5 * 60
BURST_COUNT = 10
MAX_SPEED_KMH = 900
MIN_DISTANCE_KM = 100


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def candidate_id(product, batch_no, manufacturer_key):
    # Text signatures deliberately do not claim verified legal identity.
    return digest([product.strip().casefold(), batch_no.strip().casefold(),
                   manufacturer_key.strip().casefold()])[:24]


@dataclass(frozen=True)
class ScanEvent:
    event_id: str
    pack_id: str
    product: str
    batch_no: str
    manufacturer_key: str
    event_time: str
    source_id: str
    latitude: float
    longitude: float
    simulated: bool

    @classmethod
    def parse(cls, payload):
        if not isinstance(payload, dict) or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("Event must contain exactly the documented ScanEvent fields.")
        for name in ("event_id", "pack_id", "product", "batch_no", "source_id", "manufacturer_key"):
            value = payload[name]
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError(f"Invalid {name}.")
            if name != "manufacturer_key" and not value.strip():
                raise ValueError(f"Empty {name}.")
        if not isinstance(payload["simulated"], bool):
            raise ValueError("simulated must be a boolean.")
        try:
            timestamp = datetime.fromisoformat(payload["event_time"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Event time must include a UTC offset.")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("Invalid timezone-aware event_time.") from exc
        for name, limit in (("latitude", 90), ("longitude", 180)):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Invalid {name}.")
            if not math.isfinite(value) or not -limit <= value <= limit:
                raise ValueError(f"Invalid {name}.")
        values = dict(payload)
        values["event_time"] = timestamp.astimezone(timezone.utc).isoformat()
        values["latitude"] = float(values["latitude"])
        values["longitude"] = float(values["longitude"])
        return cls(**values)

    @property
    def timestamp(self):
        return datetime.fromisoformat(self.event_time).timestamp()

    @property
    def candidate(self):
        return candidate_id(self.product, self.batch_no, self.manufacturer_key)


class ReferenceIndex:
    def __init__(self, df, priorities):
        self.rows = defaultdict(list)
        self.scores = {str(key).strip().casefold(): float(score) for key, score in
                       zip(priorities["manufacturer_key"], priorities["priority_index"])}
        fields = ["build_record_id", "product", "batch_no", "manufacturer_name_normalized", "source_category"]
        records = df[fields].to_dict("records")
        # Fingerprint reference content and scoring output, not only position-based IDs.
        self.snapshot_id = digest({"records": records, "scores": self.scores})
        for row in records:
            if str(row["batch_no"]).strip():
                key = candidate_id(row["product"], row["batch_no"], row["manufacturer_name_normalized"])
                self.rows[key].append(row)

    def evidence(self, event):
        rows = self.rows.get(event.candidate, [])
        return {
            "reference_match": bool(rows),
            "reference_status": "historical_report_match" if rows else "not_in_local_reference",
            "historical_priority": self.scores.get(event.manufacturer_key.strip().casefold(), 0.0),
            "record_ids": sorted({r["build_record_id"] for r in rows}),
            "spurious_report_match": any(r["source_category"] == "spurious" for r in rows),
        }


def distance_km(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    delta = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(delta)))


def pack_signals(observations):
    """Return strongest heuristic signal in bounded windows, not a probability."""
    ordered = sorted(observations)
    tier, max_sources, reasons = 0, 0, set()
    for i, (ts, source, lat, lon) in enumerate(ordered):
        previous = [p for p in ordered[:i] if ts-p[0] <= WINDOW_SECONDS]
        sources = {source, *(p[1] for p in previous)}
        max_sources = max(max_sources, len(sources))
        travel = False
        for old_ts, _, old_lat, old_lon in previous:
            km = distance_km(lat, lon, old_lat, old_lon)
            hours = (ts-old_ts) / 3600
            if km >= MIN_DISTANCE_KM and (hours == 0 or km/hours > MAX_SPEED_KMH):
                travel = True
                break
        burst = 1 + sum(ts-p[0] <= BURST_SECONDS for p in previous) >= BURST_COUNT
        if travel or burst:
            tier = max(tier, (3 if travel else 2) if len(sources) >= 2 else 1)
            if travel:
                reasons.add("PACK_TRAVEL_CONFLICT")
            if burst:
                reasons.add("PACK_SCAN_BURST")
    return tier, max_sources, sorted(reasons)


class InspectionStream:
    """Single SQLite writer with durable retries and time-windowed pack evidence.

    Source IDs are asserted by this local input contract, not authenticated.
    Corroboration therefore assumes independent, trustworthy source enrollment.
    """
    def __init__(self, reference, database=":memory:"):
        self.reference = reference
        self.db = sqlite3.connect(str(database), timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, candidate TEXT NOT NULL, pack_id TEXT NOT NULL,
                ts REAL NOT NULL, source_id TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
                payload TEXT NOT NULL, result TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS pack_window ON events(candidate, pack_id, ts);
            CREATE INDEX IF NOT EXISTS recent_events ON events(ts);
        """)
        expected = digest([reference.snapshot_id, POLICY_VERSION])
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('identity', ?)", (expected,))
        if self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0] != expected:
            self.db.close()
            raise ValueError("Database reference/policy differs. Use a new replay database.")

    def close(self):
        self.db.close()

    def ingest(self, payload):
        event = ScanEvent.parse(payload)
        canonical = json.dumps(asdict(event), sort_keys=True, allow_nan=False)
        # Serialize read/derive/write so concurrent connections cannot bypass idempotency.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT payload,result FROM events WHERE event_id=?",
                                       (event.event_id,)).fetchone()
            if existing:
                if existing[0] != canonical:
                    raise ValueError("Conflicting payload for an existing event_id.")
                return {**json.loads(existing[1]), "duplicate_delivery": True}
            rows = self.db.execute(
                "SELECT ts,source_id,lat,lon FROM events WHERE candidate=? AND pack_id=? AND ts BETWEEN ? AND ?",
                (event.candidate, event.pack_id, event.timestamp-WINDOW_SECONDS,
                 event.timestamp+WINDOW_SECONDS)).fetchall()
            observed = [(row[0], row[1], row[2], row[3]) for row in rows]
            observed.append((event.timestamp, event.source_id, event.latitude, event.longitude))
            tier, source_count, reasons = pack_signals(observed)
            anomaly = tier > 0
            corroborated = tier >= 2
            historical = self.reference.evidence(event)
            result = {
                **historical, "event_id": event.event_id, "candidate_id": event.candidate,
                "pack_id": event.pack_id, "event_time": event.event_time,
                "scan_anomaly": anomaly, "evidence_tier": tier,
                "asserted_source_count": source_count, "corroborated": corroborated,
                "reason_codes": reasons, "snapshot_id": self.reference.snapshot_id,
                "policy_version": POLICY_VERSION, "duplicate_delivery": False,
                "simulated": event.simulated,
            }
            if anomaly and not corroborated:
                result["reason_codes"].append("SINGLE_SOURCE_REVIEW_ONLY")
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)", (
                event.event_id, event.candidate, event.pack_id, event.timestamp,
                event.source_id, event.latitude, event.longitude, canonical,
                json.dumps(result, sort_keys=True)))
            return result

    def queue(self, capacity=10, mode="fused", as_of=None):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
            raise ValueError("capacity must be a nonnegative integer.")
        if mode not in {"fused", "history_only", "raw_volume", "scan_only"}:
            raise ValueError("Unknown queue mode.")
        if as_of is None:
            as_of = self.db.execute("SELECT MAX(ts) FROM events").fetchone()[0]
        if as_of is None:
            return []
        groups, packs = {}, defaultdict(list)
        for payload, result in self.db.execute(
                "SELECT payload,result FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts,event_id",
                (as_of-WINDOW_SECONDS, as_of)):
            event, evidence = json.loads(payload), json.loads(result)
            cid = evidence["candidate_id"]
            if cid not in groups:
                groups[cid] = {
                    "candidate_id": cid, "product": event["product"], "batch_no": event["batch_no"],
                    "manufacturer_key": event["manufacturer_key"], "event_count": 0,
                    "historical_priority": evidence["historical_priority"], "evidence_tier": 0,
                    "asserted_source_count": 0, "scan_anomaly": False,
                    "reference_status": evidence["reference_status"],
                    "spurious_report_match": evidence["spurious_report_match"],
                    "record_ids": evidence["record_ids"], "reason_codes": set(),
                    "evidence_event_ids": [], "simulated": event["simulated"],
                    "snapshot_id": self.reference.snapshot_id,
                }
            item = groups[cid]
            item["event_count"] += 1
            item["simulated"] |= event["simulated"]
            if len(item["evidence_event_ids"]) < 20:
                item["evidence_event_ids"].append(event["event_id"])
            parsed = ScanEvent.parse(event)
            packs[(cid, event["pack_id"])].append((parsed.timestamp, parsed.source_id,
                                                    parsed.latitude, parsed.longitude))
        # Recompute on the active window. Stored results remain historical audit evidence.
        for (cid, _), observations in packs.items():
            tier, source_count, reasons = pack_signals(observations)
            item = groups[cid]
            item["evidence_tier"] = max(item["evidence_tier"], tier)
            item["asserted_source_count"] = max(item["asserted_source_count"], source_count)
            item["reason_codes"].update(reasons)
            item["scan_anomaly"] |= tier > 0
        for item in groups.values():
            if item["evidence_tier"] == 1:
                item["reason_codes"].add("SINGLE_SOURCE_REVIEW_ONLY")
        def order(item):
            if mode == "history_only":
                return (-item["historical_priority"], item["candidate_id"])
            if mode == "raw_volume":
                return (-item["event_count"], item["candidate_id"])
            if mode == "scan_only":
                return (-item["evidence_tier"], item["candidate_id"])
            return (-item["evidence_tier"], -item["historical_priority"], item["candidate_id"])
        selected = sorted(groups.values(), key=order)[:capacity]
        for rank, item in enumerate(selected, 1):
            item["rank"] = rank
            item["reason_codes"] = sorted(item["reason_codes"])
            item["review_note"] = "Sampling priority only. Verify source independence and collect evidence."
        return selected


def make_scenarios(df, copies=1, seed=2026):
    """Synthetic behavior labels are separate from public regulatory findings."""
    if isinstance(copies, bool) or not isinstance(copies, int) or not 1 <= copies <= 100:
        raise ValueError("copies must be between 1 and 100.")
    rng = random.Random(seed)
    refs = df[df["batch_no"].str.strip().ne("") & df["manufacturer_name_normalized"].str.strip().ne("")]
    pairs = refs.drop_duplicates(["product", "batch_no", "manufacturer_name_normalized"])
    if len(pairs) < 6 * copies:
        raise ValueError("Need six distinct reference candidates per scenario copy.")
    indices = rng.sample(range(len(pairs)), 6 * copies)
    start = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    cities = [(13.08, 80.27), (28.61, 77.21)]  # Coarse synthetic Chennai/Delhi centroids.
    events, truth = [], {}
    scenarios = ["benign_repeat", "benign_distribution", "single_source_flood",
                 "clone_spread", "clone_burst", "slow_clone_known_miss"]
    for j, index in enumerate(indices):
        row = pairs.iloc[index]
        scenario = scenarios[j % 6]
        base = dict(product=row["product"], batch_no=row["batch_no"],
                    manufacturer_key=row["manufacturer_name_normalized"], simulated=True)
        cid = candidate_id(base["product"], base["batch_no"], base["manufacturer_key"])
        truth[cid] = {"scenario": scenario, "clone": scenario.startswith("clone_") or scenario.startswith("slow_")}
        count = 60 if scenario == "single_source_flood" else 12 if scenario == "clone_burst" else 4
        for k in range(count):
            seconds = k if scenario in {"single_source_flood", "clone_burst"} else k * 60
            if scenario == "slow_clone_known_miss":
                seconds = k * 3600
            # All copies are evaluated at one fixed end time. Slow attacks remain outside the window.
            when = start + timedelta(seconds=seconds)
            if scenario == "slow_clone_known_miss":
                when = start - timedelta(hours=3) + timedelta(seconds=seconds)
            moving = scenario in {"clone_spread", "benign_distribution", "slow_clone_known_miss"}
            lat, lon = cities[k % 2] if moving else cities[0]
            source = f"SOURCE-{j}-{k % 2}" if scenario != "single_source_flood" else f"SOURCE-{j}-0"
            pack = f"PACK-{j}-{k}" if scenario == "benign_distribution" else f"PACK-{j}"
            event = dict(base, event_id=f"EVENT-{seed}-{j}-{k}", pack_id=pack,
                         event_time=when.isoformat(), source_id=source, latitude=lat, longitude=lon)
            events.append(event)
            if scenario == "benign_repeat" and k == 0:
                events.append(dict(event))  # Exact delivery retry, not a cloned pack.
    return sorted(events, key=lambda e: (e["event_time"], e["event_id"])), truth
