"""Serve BatchGuard locally with durable case decisions and name-review history.

Start: python -m app.server. This is a loopback-only team demo service; reviewer
names are declared, not authenticated. Do not expose it as a public service.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import platform
from threading import Lock
from urllib.parse import parse_qs, unquote, urlsplit

from src.audit_store import AuditStore
from src.common import DATA_RAW, OUTPUTS, ROOT, file_hash
from src.workflow import summarize as workflow_summary
from src.identity import validate_reviews

STATUSES = {"unreviewed", "sample requested", "reviewed - no sample", "escalated to laboratory"}


def required_text(value, name, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid {name}")
    return value.strip()


def make_server(dashboard=OUTPUTS / "dashboard.html", database=ROOT / "private" / "batchguard.sqlite3", port=8000,
                live_engine=None, authority=False):
    if authority and platform.machine().lower() != "s390x":
        raise ValueError("Central approval authority requires an actual IBM Z / LinuxONE s390x host")
    dashboard = Path(dashboard)
    html = dashboard.read_text()
    payload = html.split('<script id="bg-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    dashboard_sha = file_hash(dashboard)
    pairs = {pair["pair_id"]: pair for pair in data.get("identity_candidates", [])}
    sources = {name: DATA_RAW / name for name in {r["source_file"] for c in data["candidates"].values()
               for r in c["history"] + c["reports"] + c.get("product_context", {}).get("records", [])}}
    sources.update({name: DATA_RAW / name for pair in pairs.values() for name in pair["source_files"]})
    sources.update({path.name: path for path in DATA_RAW.glob("*.xlsx")})
    store = AuditStore(database)
    write_lock = Lock()
    engine_lock = Lock()

    def refresh_dashboard():
        nonlocal html, data, dashboard_sha, pairs, sources
        # Called under write_lock. New builds become visible on browser refresh.
        current_sha = file_hash(dashboard)
        if current_sha == dashboard_sha:
            return
        current_html = dashboard.read_text()
        current_payload = current_html.split('<script id="bg-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        current_data = json.loads(current_payload)
        current_pairs = {pair["pair_id"]: pair for pair in current_data.get("identity_candidates", [])}
        current_sources = {path.name: path for path in DATA_RAW.glob("*.xlsx")}
        html, data, pairs, sources, dashboard_sha = current_html, current_data, current_pairs, current_sources, current_sha

    def engine():
        nonlocal live_engine
        with engine_lock:
            if live_engine is None:
                from src.live import LiveEngine
                live_engine = LiveEngine(store)
            return live_engine

    def live_options(query):
        if set(query) - {"backend", "strategy", "capacity", "stream"} or any(len(v) != 1 for v in query.values()):
            raise ValueError("Invalid live queue options")
        backend = query.get("backend", ["sklearn"])[0]
        return {"backend": backend, "strategy": query.get("strategy", ["protected_history"])[0],
                "capacity": int(query.get("capacity", ["10"])[0]), "stream": query.get("stream", ["demo"])[0],
                "history_share": data.get("models", {}).get(backend, {}).get("history_share", .75)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, content_type="application/json; charset=utf-8"):
            content = json.dumps(value, allow_nan=False).encode() if content_type.startswith("application/json") else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def allowed_origin(self):
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin == "http://" + host

        def do_GET(self):
            if not self.allowed_origin():
                return self.respond(403, {"error": "Use the local service origin"})
            with write_lock:
                refresh_dashboard()
            path = urlsplit(self.path).path
            if path in {"/api/live", "/api/runtime", "/api/live/decisions"}:
                try:
                    if path == "/api/runtime":
                        return self.respond(200, {**engine().receipt(), "approval_authority": authority, "approval_host_required": "s390x", "execution_role": "central approval service" if authority else "local preview"})
                    if path == "/api/live/decisions":
                        stream = parse_qs(urlsplit(self.path).query).get("stream", ["demo"])[0]
                        if stream not in {"demo", "submitted"}:
                            raise ValueError("Unknown stream")
                        records = store.latest("live_decision")
                        return self.respond(200, {value["candidate_id"]: value for value in records.values() if value["stream"] == stream})
                    return self.respond(200, engine().snapshot(**live_options(parse_qs(urlsplit(self.path).query))))
                except (ValueError, TypeError) as exc:
                    return self.respond(400, {"error": str(exc)})
            if path in {"/", "/dashboard.html"}:
                return self.respond(200, html.encode(), "text/html; charset=utf-8")
            if path == "/api/health":
                return self.respond(200, {"storage": "sqlite", "reviewer_authentication": False,
                                          "dashboard_sha256": dashboard_sha, "approval_authority": authority})
            if path == "/api/decisions":
                return self.respond(200, store.latest("decision"))
            if path == "/api/identity-reviews":
                return self.respond(200, store.latest("identity_review"))
            if path == "/api/workflow/results":
                return self.respond(200, workflow_summary(store.latest("workflow_start"), store.latest("workflow_finish")))
            if path == "/api/audit":
                try:
                    with write_lock:
                        return self.respond(200, {**store.export(), "verification": store.verify()})
                except ValueError as exc:
                    return self.respond(409, {"error": str(exc)})
            if path.startswith("/sources/"):
                source = sources.get(unquote(path.removeprefix("/sources/")))
                if source is not None and source.is_file():
                    return self.respond(200, source.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return self.respond(404, {"error": "Not found"})

        def do_POST(self):
            # Keep review-graph checks and workflow assignment atomic across clients.
            with write_lock:
                self.write_post()

        def write_post(self):
            refresh_dashboard()
            if not self.allowed_origin():
                return self.respond(403, {"error": "Cross-origin writes are rejected"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.respond(415, {"error": "Send application/json"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("Request body must be 1–32768 bytes")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Request must be a JSON object")
                path = urlsplit(self.path).path
                if path == "/api/scans":
                    if set(body) != {"event"}:
                        raise ValueError("Provide exactly one event object")
                    return self.respond(200, engine().ingest(body["event"]))
                if path == "/api/demo/run":
                    if set(body) not in ({"request_id", "backend"}, {"request_id", "backend", "csv"}):
                        raise ValueError("Provide request_id, backend and optional input CSV")
                    backend = body["backend"]
                    share = data.get("models", {}).get(backend, {}).get("history_share", .75)
                    result = engine().run_demo(body["request_id"], backend, share, body.get("csv"))
                    return self.respond(200, {**result, "approval_authority": authority, "central_approval_pending": True})
                if path == "/api/demo/scenario":
                    if set(body) != {"scenario"}:
                        raise ValueError("Provide a scenario name")
                    return self.respond(200, engine().scenario(body["scenario"]))
                if path == "/api/demo/reset":
                    if body:
                        raise ValueError("Reset takes an empty object; audit history is retained")
                    return self.respond(200, engine().reset_demo())
                request_id = required_text(body.get("request_id"), "request_id", 100)
                reviewer = required_text(body.get("reviewer_id"), "reviewer_id", 200)
                if path == "/api/approvals":
                    if not authority:
                        return self.respond(403, {"error": "This preview node cannot approve inspection queues. Run the central service on IBM Z / LinuxONE with --authority."})
                    expected = {"request_id", "reviewer_id", "backend", "stream", "revision", "queue_sha256", "capacity"}
                    if set(body) != expected:
                        raise ValueError("Invalid approval request fields")
                    previous = store.request(request_id)
                    if previous:
                        if previous["kind"] != "queue_approval" or previous["payload"].get("request") != body:
                            raise ValueError("Request ID already used for a different event")
                        return self.respond(200, {**previous["payload"], "duplicate": True})
                    snapshot = engine().snapshot(backend=body["backend"], capacity=body["capacity"], stream=body["stream"],
                                                 history_share=data.get("models", {}).get(body["backend"], {}).get("history_share", .75))
                    if type(body["revision"]) is not int or body["revision"] != snapshot["revision"] or body["queue_sha256"] != snapshot["queue_sha256"]:
                        return self.respond(409, {"error": "Queue changed. Run or refresh the case before central approval."})
                    if not snapshot["queue"]:
                        raise ValueError("Cannot approve an empty queue")
                    value = {"request": body, "machine": platform.machine(), "model_version": snapshot["model_version"],
                             "queue_sha256": snapshot["queue_sha256"], "revision": snapshot["revision"],
                             "capacity": snapshot["capacity"], "reviewer_id": reviewer,
                             "candidate_ids": [r["candidate_id"] for r in snapshot["queue"][:snapshot["capacity"]]],
                             "simulated": body["stream"] == "demo", "approval_scope": "team demonstration only; reviewer ID is self-declared"}
                    store.append(request_id, "queue_approval", snapshot["queue_sha256"], value)
                    return self.respond(200, {**value, "duplicate": False})
                if path == "/api/live/decisions":
                    expected = {"request_id", "reviewer_id", "candidate_id", "backend", "strategy", "capacity", "stream", "revision", "status", "note"}
                    if set(body) != expected or body["status"] not in STATUSES or not isinstance(body["note"], str) or len(body["note"]) > 4000:
                        raise ValueError("Invalid live decision fields")
                    original_request = {k: v for k, v in body.items() if k != "request_id"}
                    previous = store.request(request_id)
                    if previous:
                        if previous["kind"] != "live_decision" or previous["payload"].get("request") != original_request:
                            raise ValueError("Request ID already used for a different event")
                        return self.respond(200, {"sequence": previous["sequence"], "event_hash": previous["event_hash"], "duplicate": True})
                    snapshot = engine().snapshot(backend=body["backend"], strategy=body["strategy"],
                                                 capacity=body["capacity"], stream=body["stream"],
                                                 history_share=data.get("models", {}).get(body["backend"], {}).get("history_share", .75))
                    if type(body["revision"]) is not int or body["revision"] != snapshot["revision"]:
                        return self.respond(409, {"error": "New scans changed this queue. Refresh it before saving the decision."})
                    row = next((r for r in snapshot["queue"] if r["candidate_id"] == body["candidate_id"]), None)
                    if row is None:
                        raise ValueError("Candidate is not in the current live window")
                    value = {"candidate_id": row["candidate_id"], "reviewer_id": reviewer, "status": body["status"],
                             "note": body["note"], "batch": row["batch_no"], "product": row["product"],
                             "manufacturer": row["manufacturer"], "rank": row["rank"], "priority": row["priority_score"],
                             "stream": body["stream"], "revision": snapshot["revision"], "capacity": body["capacity"],
                             "strategy": body["strategy"], "model_version": snapshot["model_version"],
                             "queue_sha256": snapshot["queue_sha256"], "as_of": snapshot["as_of"],
                             "request": original_request, "machine": engine().host["machine"], "simulated_scan_context": body["stream"] == "demo"}
                    result = store.append(request_id, "live_decision", body["stream"] + ":" + row["candidate_id"], value)
                elif path == "/api/workflow/start":
                    if set(body) != {"request_id", "reviewer_id", "role"} or body["role"] not in {"inspector", "pharmacist", "researcher", "other"}:
                        raise ValueError("Provide a reviewer ID and declared role")
                    starts = store.latest("workflow_start")
                    existing = starts.get(request_id)
                    if existing:
                        if existing["reviewer_id"] != reviewer or existing["role"] != body["role"]:
                            raise ValueError("Request ID already belongs to another session")
                        return self.respond(200, existing)
                    own = [s for s in starts.values() if s["reviewer_id"] == reviewer]
                    completed = store.latest("workflow_finish")
                    active = [s for s in own if s["study_id"] not in completed]
                    if active:
                        return self.respond(200, active[-1])
                    used = {s["task"]["manufacturer"] for s in own}
                    available = [t for t in data.get("workflow_tasks", []) if t["manufacturer"] not in used]
                    if not available:
                        raise ValueError("No unused tasks remain for this participant")
                    task = secrets.choice(available)
                    # Counterbalance first method between participant IDs; alternate thereafter.
                    from src.common import digest
                    method = ("manual", "batchguard")[(int(digest(reviewer)[:8], 16) + len(own)) % 2]
                    session = {"study_id": request_id, "reviewer_id": reviewer, "role": body["role"],
                               "method": method, "task": {k: v for k, v in task.items() if k != "expected_count"},
                               "dashboard_sha256": dashboard_sha}
                    store.append(request_id, "workflow_start", request_id, session)
                    return self.respond(200, store.latest("workflow_start")[request_id])
                elif path == "/api/workflow/finish":
                    if set(body) != {"request_id", "reviewer_id", "study_id", "answer", "feedback"}:
                        raise ValueError("Invalid workflow completion fields")
                    start = store.latest("workflow_start").get(body["study_id"])
                    if start is None or start["reviewer_id"] != reviewer:
                        raise ValueError("Unknown session or mismatched reviewer")
                    if type(body["answer"]) is not int or body["answer"] < 0 or not isinstance(body["feedback"], str) or len(body["feedback"]) > 4000:
                        raise ValueError("Provide a nonnegative integer answer and feedback text")
                    previous = store.latest("workflow_finish").get(body["study_id"])
                    if previous:
                        if previous["request_id"] == request_id:
                            if previous["answer"] != body["answer"] or previous["feedback"] != body["feedback"]:
                                raise ValueError("Request ID already used for a different completion")
                            return self.respond(200, previous)
                        raise ValueError("This task has already been completed")
                    task = next(t for t in data["workflow_tasks"] if t["task_id"] == start["task"]["task_id"])
                    seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(start["saved_at"])).total_seconds()
                    result = {"reviewer_id": reviewer, "elapsed_seconds": seconds,
                              "answer": body["answer"], "correct": body["answer"] == task["expected_count"],
                              "feedback": body["feedback"], "method": start["method"], "role": start["role"]}
                    store.append(request_id, "workflow_finish", body["study_id"], result)
                    return self.respond(200, store.latest("workflow_finish")[body["study_id"]])
                elif path == "/api/decisions":
                    expected = {"request_id", "reviewer_id", "candidate_id", "backend", "step", "capacity", "status", "note", "strategy"}
                    if set(body) != expected:
                        raise ValueError("Invalid decision fields")
                    cid, backend = body["candidate_id"], body["backend"]
                    if cid not in data["candidates"] or backend not in data["backends"]:
                        raise ValueError("Unknown candidate or backend")
                    step, capacity = body["step"], body["capacity"]
                    if type(step) is not int or not 1 <= step <= len(data["feed"]) or type(capacity) is not int or not 1 <= capacity <= 1000:
                        raise ValueError("Invalid replay step or capacity")
                    if body["status"] not in STATUSES or not isinstance(body["note"], str) or len(body["note"]) > 4000:
                        raise ValueError("Invalid status or note")
                    strategy = body["strategy"]
                    if strategy not in {"legacy", "protected_history"}:
                        raise ValueError("Unknown queue strategy")
                    steps = data["protected_steps"] if strategy == "protected_history" else data["steps"]
                    ranked = steps[backend][step - 1]
                    match = next(((rank, row) for rank, row in enumerate(ranked, 1) if row[0] == cid), None)
                    if match is None:
                        raise ValueError("Candidate was not present at this replay step")
                    rank, row = match
                    candidate = data["candidates"][cid]
                    event_payload = {"reviewer_id": reviewer, "status": body["status"], "note": body["note"],
                                     "batch": candidate["batch"], "product": candidate["product"],
                                     "manufacturer": candidate["manufacturer"], "priority": row[1], "rank": rank,
                                     "capacity": capacity, "step": step, "strategy": strategy,
                                     "model_version": data["models"][backend]["version"], "backend": backend,
                                     "dashboard_sha256": dashboard_sha, "simulated_scan_context": True}
                    result = store.append(request_id, "decision", cid, event_payload)
                elif path == "/api/identity-reviews":
                    if set(body) != {"request_id", "reviewer_id", "pair_id", "decision", "evidence_ref"}:
                        raise ValueError("Invalid identity review fields")
                    pair_id = body["pair_id"]
                    if pair_id not in pairs or body["decision"] not in {"same_entity", "different_entities", "uncertain"}:
                        raise ValueError("Unknown pair or review decision")
                    pair = pairs[pair_id]
                    current_reviews = store.latest("identity_review")
                    current_reviews[pair_id] = {"left": pair["left"], "right": pair["right"], "decision": body["decision"]}
                    validate_reviews(list(current_reviews.values()))
                    result = store.append(request_id, "identity_review", pair_id,
                                          {"reviewer_id": reviewer, "decision": body["decision"],
                                           "evidence_ref": required_text(body["evidence_ref"], "evidence_ref"),
                                           "left": pair["left"], "right": pair["right"],
                                           "record_ids": pair["record_ids"], "dashboard_sha256": dashboard_sha,
                                           "changes_model_features": False})
                else:
                    return self.respond(404, {"error": "Not found"})
                return self.respond(200, result)
            except (ValueError, TypeError, KeyError) as exc:
                return self.respond(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.audit_store = store
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dashboard", type=Path, default=OUTPUTS / "dashboard.html")
    parser.add_argument("--database", type=Path, default=ROOT / "private" / "batchguard.sqlite3")
    parser.add_argument("--authority", action="store_true", help="Central queue approval role; refuses non-s390x hosts")
    args = parser.parse_args()
    server = make_server(args.dashboard, args.database, args.port, authority=args.authority)
    print(f"BatchGuard: http://127.0.0.1:{server.server_port} — private SQLite decisions; Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
