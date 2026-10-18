"""Optional browser smoke check. Requires Playwright and its Chromium browser.

Uses a temporary database. Its workflow events are automated test fixtures,
never professional feedback or field performance evidence.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
# Keep inference on the project's installed package versions when available.
project_site = ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if project_site.is_dir():
    sys.path.insert(0, str(project_site))
sys.path.insert(0, str(ROOT))
for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[variable] = "1"

from app.server import make_server
from playwright.sync_api import sync_playwright


def screenshot(page, path):
    page.screenshot(path=str(path),full_page=True,animations="disabled")


def open_tools(page):
    page.get_by_role("tab",name="Inspect",exact=True).click()
    if not page.locator("#inspectionTools").evaluate("e=>e.open"):
        page.locator("#inspectionTools > summary").click()


def main():
    with tempfile.TemporaryDirectory() as directory:
        server = make_server(database=Path(directory) / "browser-test.sqlite3", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                address = f"http://127.0.0.1:{server.server_port}"
                page.goto(address)
                page.wait_for_function("S.storage === 'server' && S.runtime !== null")
                page.evaluate("fonts => Promise.all(fonts.map(font => document.fonts.load(font)))", ['14px "Geist"', '14px "Geist Mono"'])
                assert page.evaluate("fonts => fonts.every(font => document.fonts.check(font))", ['14px "Geist"', '14px "Geist Mono"'])
                assert page.evaluate('getComputedStyle(document.body).fontFamily.startsWith("Geist")')
                assert page.get_by_role("heading",name="Know what to inspect next.",exact=True).is_visible()
                assert not page.locator("#inspectionTools").is_visible()
                print("Checking overview and embedded fonts",flush=True)
                screenshot(page,ROOT / "outputs" / "overview-desktop.png")
                page.locator("#overviewStart").click()
                page.wait_for_function("!S.demoRunning && S.demoResult !== null",timeout=60000)
                assert page.evaluate("S.demoResult.passed && S.tab === 'decision'")
                page.get_by_role("button",name="View input",exact=True).click()
                assert page.locator("#queueStrategy").input_value() == "protected_history"
                # One click consumes the included CSV and records checked demo outcomes.
                with page.expect_download() as csv_download:
                    page.get_by_role("button",name="Download input CSV",exact=True).click()
                assert csv_download.value.suggested_filename == "inspection_case.csv"
                assert len(Path(csv_download.value.path()).read_text().splitlines()) == 16
                page.locator("#startDemo").click()
                page.wait_for_function("!S.demoRunning && S.demoResult !== null",timeout=60000)
                assert page.evaluate("S.demoResult.passed && S.demoResult.input_rows === 15 && S.demoResult.before_rank > 4 && S.demoResult.after_rank === 4")
                assert page.evaluate("S.demoResult.checks.every(c=>c.passed)")
                print("CSV case checks passed",flush=True)
                assert not page.request.get(address+"/api/runtime").json()["approval_authority"]
                page.get_by_text("IBM Z central approval pending",exact=True).wait_for()
                page.locator(".export-menu > summary").click()
                with page.expect_download() as handoff:
                    page.get_by_role("button",name="Download IBM Z handoff",exact=True).click()
                assert json.loads(Path(handoff.value.path()).read_text())["required_authority"] == "s390x"
                page.get_by_role("button",name="Open case evidence",exact=True).click()
                assert "SCRIPTED DEMONSTRATION" in page.get_by_placeholder("Note for the record (optional)").input_value()
                page.get_by_role("button",name="Close evidence",exact=True).click()
                # CSV edits must change inference rather than force a successful screen.
                if not page.get_by_label("Input CSV",exact=True).is_visible():
                    page.get_by_text("View or edit the input",exact=True).click()
                original=page.get_by_label("Input CSV",exact=True).input_value()
                page.get_by_label("Input CSV",exact=True).fill(original.replace("28.61,77.21","13.08,80.27"))
                page.locator("#startDemo").click()
                page.wait_for_function("!S.demoRunning && S.demoResult !== null",timeout=60000)
                assert page.evaluate("!S.demoResult.passed && S.demoResult.checks.some(c=>c.id === 'travel_alert' && !c.passed)")
                try:
                    page.get_by_role("button",name="Restore included CSV",exact=True).click(timeout=6000)
                except Exception:
                    page.screenshot(path="/tmp/batchguard-click-failure.png",full_page=True)
                    print(page.get_by_role("button",name="Restore included CSV",exact=True).evaluate("e=>{const r=e.getBoundingClientRect();return {rect:[r.x,r.y,r.width,r.height],hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.outerHTML.slice(0,250),parents:[...function*(n){while(n){yield n;n=n.parentElement;}}(e)].map(n=>({tag:n.tagName,cls:n.className,open:n.open,rect:n.getBoundingClientRect().toJSON()}))}}"))
                    raise
                print("CSV editing checked",flush=True)
                page.get_by_role("button",name="Recorded replay",exact=True).click()
                before=page.evaluate("S.capacity")
                page.get_by_role("button",name="More",exact=True).click()
                assert page.evaluate("S.capacity") == before+1
                page.get_by_role("button",name="Fewer",exact=True).click()
                page.get_by_title("Start of feed (Home)").click()
                page.get_by_title("Next scan (→)").click()
                assert page.evaluate("S.k === 2")
                page.get_by_title("End of feed (End)").click()

                page.locator("#demoBtn").click()
                page.get_by_role("button", name="Source evidence", exact=True).click()
                page.get_by_label("Reviewer ID", exact=True).fill("automated-browser-test")
                page.get_by_role("button", name="Sample requested", exact=True).click()
                page.get_by_role("button", name="Save decision", exact=True).click()
                page.get_by_text("✓ Saved to SQLite", exact=True).wait_for()
                page.get_by_role("button", name="Close evidence", exact=True).click()
                page.reload()
                page.wait_for_function("S.storage === 'server'")
                assert page.evaluate("Object.values(S.reviews).some(r => r.reviewer_id === 'automated-browser-test')")
                open_tools(page)
                page.locator("#queueStrategy").select_option("legacy")
                assert page.evaluate("stepRows()[0].scan > 0")
                page.locator("#queueStrategy").select_option("protected_history")
                page.get_by_role("button",name="Live operations",exact=True).click()
                page.wait_for_function("S.mode === 'live' && !S.liveBusy && S.live !== null")
                page.get_by_role("button",name="Reset demo",exact=True).click()
                page.wait_for_function("!S.actionBusy && !S.liveBusy && S.live?.queue.length === 0")
                page.locator(".advanced-scenarios summary").click()
                page.get_by_role("button",name="Load demo",exact=True).click()
                page.wait_for_function("!S.liveBusy && S.live?.queue.length === 6")
                assert page.evaluate("stepRows().every(r => r.scan === 0)")
                page.get_by_role("button",name="Location conflict",exact=True).click()
                page.wait_for_function("!S.liveBusy && S.live?.queue.some(r=>r.scan_alert)")
                assert page.evaluate("S.live.events.length === 8 && stepRows().some(r=>r.scan > 0)")
                page.get_by_role("button",name="Routine scan",exact=True).click()
                page.wait_for_function("!S.actionBusy && !S.liveBusy && S.live?.events.length === 9")
                assert page.evaluate("S.live.queue.length === 7")
                page.get_by_role("button",name="Repeated-pack burst",exact=True).click()
                page.wait_for_function("!S.actionBusy && !S.liveBusy && S.live?.events.length === 21")
                assert page.evaluate("S.live.queue.some(r=>r.reason_codes.includes('REPEATED_PACK_BURST_REVIEW'))")
                assert page.get_by_role("button",name="Routine scan",exact=True).is_enabled()
                print("All scan buttons checked",flush=True)

                page.locator(".queue tbody tr.alert").first.click()
                page.get_by_label("Reviewer ID",exact=True).fill("automated-live-test")
                page.get_by_role("button",name="Sample requested",exact=True).click()
                page.get_by_role("button",name="Save decision",exact=True).click()
                page.get_by_text("✓ Saved to SQLite",exact=True).wait_for()
                page.get_by_role("button",name="Close evidence",exact=True).click()
                page.locator(".runtime-details > summary").click()
                with page.expect_download() as receipt_download:
                    page.get_by_role("button",name="Download runtime receipt",exact=True).click()
                assert receipt_download.value.suggested_filename == "batchguard-runtime-receipt.json"
                page.evaluate("scrollTo(0,0)")
                page.locator("#inspectionTools > summary").click()
                screenshot(page,ROOT / "outputs" / "operations-desktop.png")
                open_tools(page)
                page.get_by_label("Observation stream").select_option("submitted")
                page.wait_for_function("!S.liveBusy && S.live?.stream === 'submitted'")
                assert page.evaluate("stepRows().length === 0")
                page.get_by_role("button",name="Recorded replay",exact=True).click()
                source = page.evaluate("Object.values(D.candidates).flatMap(c => c.history)[0].source_file")
                response = page.request.get(address + "/sources/" + source)
                assert response.status == 200 and len(response.body()) > 1000
                page.get_by_role("tab", name="Data", exact=True).click()
                page.get_by_role("heading", name="Official-source cross-check", exact=True).wait_for()
                page.get_by_role("heading", name="What if reports arrive later?", exact=True).wait_for()
                assert page.evaluate("D.source_audit.exact_field_matches === 2451 && D.source_audit.unmatched_local_records === 100")
                first = page.locator("#data details").first
                first.locator("summary").click()
                first.get_by_label("Name review reviewer ID").fill("automated-browser-test")
                first.get_by_label("Identity review outcome").select_option("uncertain")
                first.get_by_label("Name link evidence").fill("Automated fixture in temporary database; no identity assertion.")
                first.get_by_role("button", name="Save name review").click()
                first.get_by_text("Review saved to SQLite.", exact=False).wait_for()
                page.get_by_label("Workflow participant ID").fill("automated-test-participant")
                page.get_by_role("button", name="Start / resume task").click()
                page.get_by_label("Workflow task answer").wait_for()
                audit = page.request.get(address + "/api/audit").json()
                start = next(event["payload"] for event in reversed(audit["events"]) if event["kind"] == "workflow_start")
                count = page.evaluate("id => D.workflow_tasks.find(t => t.task_id === id).expected_count", start["task"]["task_id"])
                page.get_by_label("Workflow task answer").fill(str(count))
                page.get_by_label("Workflow task feedback").fill("Automated test only; not human evaluation evidence.")
                page.get_by_role("button", name="Submit answer and stop timer").click()
                page.get_by_text("Task saved:", exact=False).wait_for()
                assert page.request.get(address + "/api/workflow/results").json()["completed_tasks"] == 1
                page.get_by_role("tab", name="Inspect", exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role("button", name="Export audit", exact=True).click()
                assert download.value.suggested_filename == "batchguard-audit.json"
                page.set_viewport_size({"width": 390, "height": 844})
                page.reload()
                page.wait_for_function("S.storage === 'server'")
                screenshot(page,ROOT / "outputs" / "overview-mobile.png")
                open_tools(page)
                assert page.locator("#queueStrategy").is_visible()
                page.get_by_role("button",name="Live operations",exact=True).click()
                page.wait_for_function("!S.liveBusy && S.live !== null")
                page.get_by_label("Observation stream").select_option("demo")
                page.wait_for_function("!S.liveBusy && S.live?.stream === 'demo'")
                page.evaluate("scrollTo(0,0)")
                page.locator("#inspectionTools > summary").click()
                screenshot(page,ROOT / "outputs" / "operations-mobile.png")
                overflow = page.evaluate("[...document.querySelectorAll('body *')].filter(e=>!e.closest('dialog') && !e.closest('.scroll-x') && e.getBoundingClientRect().right > innerWidth + 1).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,text:e.textContent.slice(0,80)}))")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), json.dumps(overflow)
                page.locator(".queue tbody tr.alert").first.click()
                assert page.get_by_role("dialog").is_visible()
                page.get_by_role("button",name="Close evidence",exact=True).click()
                # Standalone HTML: Start replays the build-time case without claiming live execution.
                offline=browser.new_page(viewport={"width":1440,"height":1000})
                offline.on("pageerror",lambda error: errors.append(str(error)))
                offline.goto((ROOT / "outputs" / "dashboard.html").as_uri())
                offline.locator("#overviewStart").click()
                offline.wait_for_function("!S.demoRunning && S.demoResult !== null")
                assert offline.evaluate("S.fixturePreview && S.demoResult.passed && S.storage === 'browser'")
                offline.get_by_text("OFFLINE REPLAY:",exact=False).wait_for()
                offline.get_by_role("button",name="Open case evidence",exact=True).click()
                assert offline.get_by_role("dialog").is_visible()
                offline.get_by_role("button",name="Close evidence",exact=True).click()
                assert not errors, errors
                print(json.dumps({"browser_errors": errors, "simple_overview_and_disclosure": True, "csv_start_and_changed_input": True, "offline_start": True, "z_authority_pending": True, "desktop_and_mobile": True, "live_queue_and_stream_isolation": True, "runtime_receipt": True,
                                  "decisions_persist": True, "source_downloads": True,
                                  "source_and_lag_panels": True, "name_reviews": True,
                                  "timed_test_task": True, "audit_export": True}))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
