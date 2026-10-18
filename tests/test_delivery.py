from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

import pandas as pd

from app.server import make_server
from src.audit_store import AuditStore
from src.identity import suggestions, validate_reviews
from src.planning import plan_candidates, protected_order


class PlanningTests(unittest.TestCase):
    def test_reservation_preserves_history_in_small_budgets_and_is_prefix_consistent(self):
        history = list(range(30, 0, -1))
        scan = [0] * 15 + [100] * 15
        ids = [f"c{i:02d}" for i in range(30)]
        result = protected_order(history, scan, [50] * 30, ids, .75)
        self.assertEqual(len({i for i, lane in result}), 30)
        self.assertEqual(sum(lane == "history" for _, lane in result[:10]), 8)
        self.assertEqual(sum(lane == "history" for _, lane in result[:25]), 19)
        self.assertEqual(result[0][0], 0)
        self.assertGreaterEqual(result[3][0], 15)

    def test_empty_lanes_fall_back_without_inventing_history(self):
        result = protected_order([0, 0, 0], [0, 100, 0], [0, 50, 0], ["a", "b", "c"])
        self.assertEqual(result[0], (1, "scan review"))
        self.assertEqual([lane for _, lane in result[1:]], ["coverage unknown"] * 2)
        with self.assertRaises(ValueError):
            protected_order([1], [1], [1], ["a"], 0)

    def test_live_candidate_planner_matches_shared_order(self):
        rows = [{"candidate_id": str(i), "historical_risk": 10 - i,
                 "scan_anomaly": 100 if i > 4 else 0, "evidence_quality": 50} for i in range(10)]
        planned = plan_candidates(rows, .75)
        self.assertEqual([r["rank"] for r in planned], list(range(1, 11)))
        self.assertEqual([r["candidate_id"] for r in planned[:4]], ["0", "1", "2", "5"])


class IdentityTests(unittest.TestCase):
    def test_reviewed_transitive_links_cannot_contradict_a_rejection(self):
        reviews = [{"left": "A", "right": "B", "decision": "same_entity"},
                   {"left": "B", "right": "C", "decision": "same_entity"}]
        validate_reviews(reviews)
        with self.assertRaisesRegex(ValueError, "conflict"):
            validate_reviews(reviews + [{"left": "A", "right": "C", "decision": "different_entities"}])

    def test_proposals_exclude_future_records_and_conflicting_postcodes(self):
        rows = [dict(collection_month=month, manufacturer_name_normalized=name,
                     build_record_id=str(i), source_file=month + ".xlsx")
                for i, (month, name) in enumerate([
                    ("2026-01", "FIRM PHARMA NO 15 STREET 600001"),
                    ("2026-02", "FIRM PHARMA NO-15 STREET 600001"),
                    ("2026-02", "FIRM PHARMA NO 15 STREET 600002"),
                    ("2026-09", "FIRM PHARMA NO.15 STREET 600001")])]
        frame = pd.DataFrame(rows)
        result = suggestions(frame, "2026-03")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["record_ids"], ["0", "1"])
        self.assertEqual(result[0]["status"], "unreviewed")
        self.assertEqual(len(frame), 4)


class AuditTests(unittest.TestCase):
    def test_idempotency_persistence_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.sqlite3"
            store = AuditStore(path)
            first = store.append("request1", "decision", "case1", {"status": "sample requested"})
            duplicate = store.append("request1", "decision", "case1", {"status": "sample requested"})
            self.assertEqual(first["event_hash"], duplicate["event_hash"])
            self.assertTrue(duplicate["duplicate"])
            with self.assertRaises(ValueError):
                store.append("request1", "decision", "case1", {"status": "changed"})
            store = AuditStore(path)
            self.assertEqual(store.verify(first["event_hash"])["events"], 1)
            with store.connect() as db:
                db.execute("UPDATE events SET payload='{}'")
            with self.assertRaisesRegex(ValueError, "chain failed"):
                store.verify()

    def test_external_anchor_detects_history_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AuditStore(Path(directory) / "cases.sqlite3")
            store.append("one", "decision", "a", {})
            head = store.append("two", "decision", "b", {})["event_hash"]
            with store.connect() as db:
                db.execute("DELETE FROM events WHERE sequence=2")
            with self.assertRaisesRegex(ValueError, "anchor"):
                store.verify(head)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        candidate = {"product": "Product", "batch": "B1", "manufacturer": "FIRM A", "history": [], "reports": []}
        row = ["case1", 10, 20, 0, 0, .1, .2, []]
        task = {"task_id": "task1", "candidate_id": "case1", "manufacturer": "FIRM A", "question": "Count?",
                "before": "2026-09", "expected_count": 2, "source_files": []}
        self.data = {"candidates": {"case1": candidate}, "backends": ["sklearn"], "feed": [{}],
                     "steps": {"sklearn": [[row]]}, "protected_steps": {"sklearn": [[row + ["history"]]]},
                     "models": {"sklearn": {"version": "v1"}}, "identity_candidates": [
                         {"pair_id": "pair1", "left": "FIRM A", "right": "FIRM-A", "record_ids": ["r1"], "source_files": []}],
                     "workflow_tasks": [task, {**task, "task_id": "task2", "manufacturer": "FIRM B"}]}
        self.dashboard = self.root / "dashboard.html"
        self.dashboard.write_text('<script id="bg-data" type="application/json">' + json.dumps(self.data) + '</script>')
        self.database = self.root / "cases.sqlite3"
        self.start()

    def start(self):
        self.server = make_server(self.dashboard, self.database, 0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop()
        self.temporary.cleanup()

    def test_rebuilt_dashboard_is_served_without_restarting(self):
        _, before = self.request("/api/health")
        self.data["models"]["sklearn"]["version"] = "v2"
        self.dashboard.write_text('<script id="bg-data" type="application/json">' + json.dumps(self.data) + '</script>')
        status, after = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertNotEqual(before["dashboard_sha256"], after["dashboard_sha256"])
        status, _ = self.request("/api/decisions", {"request_id":"reloaded", "reviewer_id":"test-reviewer",
            "candidate_id":"case1", "backend":"sklearn", "step":1, "capacity":10,
            "strategy":"protected_history", "status":"sample requested", "note":"Reload check"})
        self.assertEqual(status, 200)
        _, reviews = self.request("/api/decisions")
        self.assertEqual(reviews["case1"]["model_version"], "v2")

    def request(self, path, body=None, origin=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        connection.request("POST" if body is not None else "GET", path,
                           json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        value = json.loads(response.read())
        status = response.status
        connection.close()
        return status, value

    def decision(self, **changes):
        return {"request_id": "save1", "reviewer_id": "reviewer1", "candidate_id": "case1", "backend": "sklearn",
                "step": 1, "capacity": 10, "status": "sample requested", "note": "Evidence reviewed", "strategy": "protected_history", **changes}

    def test_saved_decisions_survive_server_restart_with_server_context(self):
        self.assertEqual(self.request("/api/decisions", self.decision())[0], 200)
        self.assertTrue(self.request("/api/decisions", self.decision())[1]["duplicate"])
        self.stop()
        self.start()
        status, rows = self.request("/api/decisions")
        self.assertEqual(status, 200)
        self.assertEqual(rows["case1"]["rank"], 1)
        self.assertEqual(rows["case1"]["model_version"], "v1")
        self.assertTrue(self.request("/api/audit")[1]["verification"]["valid"])

    def test_rejects_cross_origin_bad_candidate_and_untrusted_rank(self):
        self.assertEqual(self.request("/api/decisions", self.decision(), "https://untrusted.example")[0], 403)
        self.assertEqual(self.request("/api/decisions", self.decision(candidate_id="missing"))[0], 400)
        self.assertEqual(self.request("/api/decisions", self.decision(rank=999))[0], 400)
        self.assertEqual(self.request("/sources/../../private/cases.sqlite3")[0], 404)

    def test_name_review_records_provenance_without_merging_models(self):
        body = {"request_id": "link1", "reviewer_id": "reviewer1", "pair_id": "pair1",
                "decision": "uncertain", "evidence_ref": "Workbook r1; independent identity evidence absent"}
        self.assertEqual(self.request("/api/identity-reviews", body)[0], 200)
        review = self.request("/api/identity-reviews")[1]["pair1"]
        self.assertFalse(review["changes_model_features"])
        self.assertEqual(review["record_ids"], ["r1"])

    def test_workflow_pilot_starts_empty_times_answers_and_alternates_methods(self):
        self.assertEqual(self.request("/api/workflow/results")[1]["completed_tasks"], 0)
        methods, names = [], []
        for index in range(2):
            status, session = self.request("/api/workflow/start", {"request_id": f"start{index}", "reviewer_id": "participant1", "role": "other"})
            self.assertEqual(status, 200)
            self.assertNotIn("expected_count", session["task"])
            methods.append(session["method"]); names.append(session["task"]["manufacturer"])
            body = {"request_id": f"finish{index}", "reviewer_id": "participant1", "study_id": session["study_id"], "answer": 2, "feedback": "Test fixture only"}
            status, result = self.request("/api/workflow/finish", body)
            self.assertEqual(status, 200)
            self.assertTrue(result["correct"])
            self.assertGreaterEqual(result["elapsed_seconds"], 0)
            self.assertEqual(self.request("/api/workflow/finish", body)[0], 200)
            self.assertEqual(self.request("/api/workflow/finish", {**body, "answer": 3})[0], 400)
        self.assertEqual(set(methods), {"manual", "batchguard"})
        self.assertEqual(len(set(names)), 2)
        self.assertEqual(self.request("/api/workflow/results")[1]["completed_tasks"], 2)


if __name__ == "__main__":
    unittest.main()
