"""Exercise real saved-model inference and the live service contract on isolated state."""
from datetime import datetime, timezone
from http.client import HTTPConnection
import json
from pathlib import Path
import platform
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from app.server import make_server
from src.audit_store import AuditStore
from src.live import LiveEngine, WINDOW
from src.demo_input import DEMO_CSV, parse_demo_csv
from src.planning import plan_candidates
from scripts.package_linuxone import build, verify


class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared_temp = tempfile.TemporaryDirectory()
        cls.reference = LiveEngine(AuditStore(Path(cls.shared_temp.name) / 'reference.db'))
        cls.now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc).timestamp()

    @classmethod
    def tearDownClass(cls):
        cls.shared_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = AuditStore(Path(self.temp.name) / 'live.db')
        self.engine = LiveEngine(self.store, self.reference.df, self.reference.models, now=lambda: self.now)

    def event(self, **changes):
        row = self.reference.df.iloc[0]
        return {"event_id":"e1", "pack_id":"p1", "product":row['product'], "batch_no":row['batch_no'],
                "manufacturer_key":row['manufacturer_name_normalized'],
                "event_time":datetime.fromtimestamp(self.now, timezone.utc).isoformat(),
                "source_id":"reader1", "latitude":13.08,"longitude":80.27,"simulated":False, **changes}

    def test_idempotency_conflict_restart_and_stream_isolation(self):
        event = self.event()
        first = self.engine.ingest(event)
        self.assertFalse(first['duplicate'])
        self.assertTrue(self.engine.ingest(event)['duplicate'])
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            self.engine.ingest({**event, 'pack_id':'different'})
        self.engine.ingest({**event, 'simulated':True})
        self.engine.reset_demo()
        restored = LiveEngine(self.store, self.reference.df, self.reference.models, now=lambda:self.now)
        self.assertEqual(len(restored.streams['submitted']), 1)
        self.assertEqual(len(restored.streams['demo']), 0)
        self.assertTrue(restored.ingest({**event, 'simulated':True})['duplicate'])
        self.assertEqual(len(self.store.export()['events']),3)
        self.assertTrue(self.store.verify()['valid'])

    def test_stale_future_and_invalid_events_rejected(self):
        for offset in (-WINDOW-1, 61):
            with self.assertRaises(ValueError):
                self.engine.ingest(self.event(event_time=datetime.fromtimestamp(self.now+offset,timezone.utc).isoformat()))
        with self.assertRaises(ValueError):
            self.engine.ingest(self.event(simulated='false'))
        self.assertEqual(len(self.store.export()['events']),0)

    def test_real_inference_scenario_and_host_receipt(self):
        self.engine.scenario('seed')
        before = self.engine.snapshot()
        self.assertEqual(len(before['queue']),6)
        self.assertFalse(any(r['scan_alert'] for r in before['queue']))
        self.engine.scenario('travel')
        snapshot = self.engine.snapshot()
        alerted = [r for r in snapshot['queue'] if r['scan_alert']]
        self.assertEqual(len(alerted),1)
        self.assertIn('CLONE_PATTERN_TRAVEL_REVIEW',alerted[0]['reason_codes'])
        self.assertTrue(snapshot['candidates'][alerted[0]['candidate_id']]['reports'])
        self.assertEqual(snapshot['queue'],plan_candidates(snapshot['queue'],.75))
        receipt=self.engine.receipt()
        self.assertEqual(receipt['environment']['machine'],platform.machine())
        self.assertEqual(receipt['running_on_s390x'],platform.machine().lower()=='s390x')
        self.assertEqual(receipt['accepted_scans_this_process'],8)
        self.assertGreater(receipt['queue_measurements']['p95_ms'],0)
        self.assertFalse(receipt['hardware_acceleration_verified'])
        self.assertEqual(len(self.engine.snapshot(stream='submitted')['queue']),0)

    def test_expiry_removes_candidates_without_losing_audit(self):
        self.engine.ingest(self.event())
        self.now += WINDOW+1
        self.assertEqual(self.engine.snapshot(stream='submitted')['queue'],[])
        self.assertEqual(len(self.store.export()['events']),1)

    def test_one_click_case_checks_real_outcomes_and_is_idempotent(self):
        self.engine.ingest(self.event())
        result=self.engine.run_demo("fixed-case")
        self.assertTrue(result["passed"],result["checks"])
        self.assertGreater(result["before_rank"],4)
        self.assertEqual((result["after_rank"],result["capacity"]),(4,4))
        self.assertEqual(result["input_rows"],15)
        self.assertEqual(result["input_csv"],DEMO_CSV.read_text())
        self.assertEqual(len(result["snapshot"]["events"]),14)
        self.assertEqual(len(self.engine.streams["submitted"]),1)
        size=len(self.store.export()["events"])
        self.assertTrue(self.engine.run_demo("fixed-case")["duplicate"])
        self.assertEqual(len(self.store.export()["events"]),size)
        review=self.store.latest("live_decision")["demo:"+result["candidate_id"]]
        self.assertTrue(review["scripted_demo"])
        self.assertEqual(review["reviewer_id"],"scripted-demo")
        self.assertTrue(self.store.verify()["valid"])

    def test_demo_reports_failure_and_does_not_save_action_when_source_evidence_missing(self):
        original=self.engine.evidence
        def missing_rows(ranked,month):
            candidates=original(ranked,month)
            for candidate in candidates.values():
                for row in candidate["reports"]:
                    row.pop("source_excel_rows_json",None)
            return candidates
        with patch.object(self.engine,"evidence",side_effect=missing_rows):
            result=self.engine.run_demo("broken-source-case")
        self.assertFalse(result["passed"])
        self.assertFalse(next(c for c in result["checks"] if c["id"]=="source")["passed"])
        self.assertEqual(self.store.latest("live_decision"),{})

    def test_csv_is_consumed_and_invalid_csv_does_not_reset_or_write(self):
        text=DEMO_CSV.read_text()
        parsed=parse_demo_csv(text,self.now,"csv-test")
        self.assertEqual(len(parsed),15)
        self.assertEqual(parsed[12][1],parsed[14][1])
        self.engine.ingest(self.event(simulated=True))
        before=len(self.store.export()["events"])
        with self.assertRaises(ValueError):
            self.engine.run_demo("invalid-input",csv_text=text.replace(",true",",false"))
        self.assertEqual(len(self.store.export()["events"]),before)
        self.assertEqual(len(self.engine.streams["demo"]),1)
        # A valid changed input changes the observed rule outcome, not just the displayed filename.
        changed=text.replace("28.61,77.21","13.08,80.27")
        result=self.engine.run_demo("changed-input",csv_text=changed)
        self.assertFalse(result["passed"])
        self.assertFalse(next(c for c in result["checks"] if c["id"]=="travel_alert")["passed"])
        self.assertEqual(self.store.latest("live_decision"),{})

    def test_central_authority_refuses_non_z_host(self):
        with patch("app.server.platform.machine",return_value="x86_64"):
            with self.assertRaisesRegex(ValueError,"actual IBM Z"):
                make_server(database=self.store.path,port=0,authority=True)

    def test_live_decision_retry_and_stale_revision(self):
        server=make_server(database=self.store.path, port=0, live_engine=self.engine)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def request(method,path,body=None):
                connection=HTTPConnection('127.0.0.1',server.server_port)
                connection.request(method,path,json.dumps(body) if body is not None else None,
                                   {'Content-Type':'application/json'} if body is not None else {})
                response=connection.getresponse();value=json.loads(response.read());status=response.status;connection.close()
                return status,value
            self.assertEqual(request('POST','/api/approvals',{'request_id':'approval-test','reviewer_id':'automated-test'})[0],403)
            self.assertFalse(request('GET','/api/runtime')[1]['approval_authority'])
            status,case=request('POST','/api/demo/run',{'request_id':'api-case','backend':'sklearn','csv':DEMO_CSV.read_text()})
            self.assertEqual(status,200)
            self.assertTrue(case['passed'])
            self.assertTrue(case['central_approval_pending'])
            self.assertFalse(case['approval_authority'])
            self.engine.reset_demo()
            self.assertEqual(request('POST','/api/demo/scenario',{'scenario':'seed'})[0],200)
            status,snapshot=request('GET','/api/live')
            self.assertEqual(status,200)
            body={'request_id':'decision-1','reviewer_id':'automated-test','candidate_id':snapshot['queue'][0]['candidate_id'],
                  'backend':'sklearn','strategy':'protected_history','capacity':10,'stream':'demo',
                  'revision':snapshot['revision'],'status':'sample requested','note':'Test only'}
            self.assertEqual(request('POST','/api/live/decisions',body)[0],200)
            self.engine.scenario('routine')
            status,retry=request('POST','/api/live/decisions',body)
            self.assertEqual(status,200);self.assertTrue(retry['duplicate'])
            self.assertEqual(request('POST','/api/live/decisions',{**body,'request_id':'decision-2'})[0],409)
            self.assertEqual(request('POST','/api/live/decisions',{**body,'note':'conflict'})[0],400)
            status,reviews=request('GET','/api/live/decisions?stream=demo')
            review=reviews[body['candidate_id']]
            self.assertEqual(review['machine'],platform.machine())
            self.assertEqual(review['queue_sha256'],snapshot['queue_sha256'])
            self.assertEqual(request('GET','/api/live/decisions?stream=submitted')[1],{})
        finally:
            server.shutdown();server.server_close();thread.join()


class BundleTests(unittest.TestCase):
    def test_archive_is_deterministic_excludes_state_and_checks_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('src/a.py','private/cases.jsonl','outputs/field_model/field_model_card.json',
                         'outputs/models/sklearn/model_card.json','.env','data/raw/source.xlsx'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
            (root/'src'/'linked.py').symlink_to(root/'.env')
            result=build(root,root/'bundle.tar.gz')
            self.assertEqual(result['files_verified'],3)
            repeated=build(root,root/'second.tar.gz')
            self.assertEqual(result['archive_sha256'],repeated['archive_sha256'])
            self.assertEqual(verify(root/'bundle.tar.gz')['files_verified'],3)

    def test_zip_keeps_runtime_and_not_development_material(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runtime=('README.md','app/maps/SOURCES.txt','scripts/launch_linuxone.sh')
            excluded=('docs/pitch.md','private/reviews.sqlite','tests/test_example.py',
                      'scripts/check_browser.py','outputs/overview.png')
            for name in runtime+excluded:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name)
            result=build(root,root/'upload.zip')
            self.assertEqual(result['files_verified'],len(runtime))
            self.assertEqual(result['archive_sha256'],build(root,root/'again.zip')['archive_sha256'])
            with zipfile.ZipFile(root/'upload.zip') as archive:
                self.assertEqual(set(archive.namelist()),{'BatchGuard/'+name for name in runtime}|{'BatchGuard/BUNDLE_MANIFEST.json'})
            self.assertEqual(verify(root/'upload.zip')['files_verified'],len(runtime))
