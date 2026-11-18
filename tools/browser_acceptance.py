"""Run browser-level dashboard interaction tests against the real FastAPI app.

Requires optional development dependencies and a local Chromium installation:
    pip install -r requirements-dev.txt
    playwright install chromium
    python tools/browser_acceptance.py

The browser runs the shipped HTML/CSS/JS. Browser fetches are routed through
FastAPI's in-process TestClient because some locked-down environments prohibit
Chromium from opening localhost ports. Backend endpoint logic is not mocked.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import shutil
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_inline_page() -> str:
    html = (ROOT / "frontend" / "index.html").read_text()
    css = (ROOT / "frontend" / "style.css").read_text()
    js = (ROOT / "frontend" / "app.js").read_text()
    html = re.sub(
        r'<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"[^>]*>',
        "", html,
    )
    html = html.replace(
        '<link rel="stylesheet" href="/static/style.css">',
        "<style>" + css + "</style>",
    )
    html = re.sub(
        r'<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"[^>]*></script>',
        "", html,
    )
    html = html.replace(
        '<script src="/static/app.js"></script>',
        "<script>" + js + "</script>",
    )
    return html.replace("<head>", '<head><base href="http://omnifleet.test/">')


def run() -> dict:
    from backend import db, main  # imported after ROOT is added to sys.path

    errors: list[str] = []
    api_calls: list[tuple[str, str, int]] = []
    groups: list[str] = []
    with tempfile.TemporaryDirectory(prefix="omnifleet-ui-") as temp_dir:
        db.DB_PATH = Path(temp_dir) / "ui-acceptance.sqlite3"
        with TestClient(main.app) as client:
            def fulfill_api(route) -> None:
                request = route.request
                parsed = urlparse(request.url)
                payload = request.post_data
                kwargs = {}
                if payload:
                    try:
                        kwargs["json"] = json.loads(payload)
                    except json.JSONDecodeError:
                        kwargs["content"] = payload
                response = client.request(
                    request.method,
                    parsed.path + ("?" + parsed.query if parsed.query else ""),
                    **kwargs,
                )
                api_calls.append((request.method, parsed.path, response.status_code))
                route.fulfill(
                    status=response.status_code,
                    body=response.content,
                    headers={"content-type": response.headers.get("content-type", "application/json")},
                )

            with sync_playwright() as playwright:
                chromium_path = next((shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome") if shutil.which(name)), None)
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=chromium_path,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.new_page(viewport={"width": 1600, "height": 1100})
                page.on("pageerror", lambda error: errors.append("pageerror: " + str(error)))
                page.on(
                    "console",
                    lambda message: errors.append("console: " + message.text)
                    if message.type == "error" else None,
                )
                page.route("http://omnifleet.test/api/**", fulfill_api)
                page.set_content(build_inline_page(), wait_until="domcontentloaded")
                page.wait_for_timeout(1300)
                assert page.locator("#fleet .vehicle-card").count() == 3
                groups.append("dashboard boot and initial fleet render")

                # Help modal: open, close, reopen, jump to a section.
                page.locator("#help-open").click()
                assert page.locator("#help-dialog").evaluate("element => element.open")
                page.locator("#help-close").click()
                assert not page.locator("#help-dialog").evaluate("element => element.open")
                page.locator("#help-open").click()
                page.locator("[data-help-jump]").first.click()
                assert not page.locator("#help-dialog").evaluate("element => element.open")
                page.locator("#help-open").click()
                page.keyboard.press("Escape")
                assert not page.locator("#help-dialog").evaluate("element => element.open")

                # Every primary in-page sidebar destination must exist and respond to a click.
                page.evaluate("""() => {
                    window.__navClick = null;
                    document.querySelector('.nav-list').addEventListener('click', event => {
                        const anchor = event.target.closest('a.nav-item');
                        if (anchor) { window.__navClick = anchor.getAttribute('href'); event.preventDefault(); }
                    }, {capture:true});
                }""")
                for link in page.locator(".nav-list a.nav-item").all():
                    href = link.get_attribute("href")
                    target_id = href.lstrip("#")
                    assert href.startswith("#") and page.locator(f"#{target_id}").count() == 1, href
                    link.click()
                    assert page.evaluate("window.__navClick") == href, href
                groups.append("operator help open, close, Escape and all sidebar navigation links")

                # All seven map layer controls must toggle state without JS errors.
                for layer in ("routes", "zones", "labels", "sensors", "comms", "objects", "observations"):
                    button = page.locator(f'[data-layer="{layer}"]')
                    before = "active" in (button.get_attribute("class") or "")
                    button.click()
                    after = "active" in (button.get_attribute("class") or "")
                    assert after != before, f"Layer toggle failed: {layer}"
                    button.click()
                groups.append("all seven map overlay toggles")

                # The three prompt examples populate the command composer.
                for button in page.locator("[data-cmd]").all():
                    button.click()
                    assert page.locator("#cmd").input_value() == button.get_attribute("data-cmd")
                groups.append("all three mission prompt presets")

                # Fallback map fit and waypoint tasking -> pending proposal -> reject.
                page.locator("#map-fit").click()
                assert "FULL THEATRE" in page.locator("#map-tasking-status").inner_text()
                page.locator("#map-vehicle").select_option("scout-1")
                page.locator("#map-tasking").click()
                map_box = page.locator("#map-fallback").bounding_box()
                page.mouse.click(map_box["x"] + map_box["width"] * .50, map_box["y"] + map_box["height"] * .50)
                page.wait_for_timeout(80)
                assert "PENDING" in page.locator("#status").inner_text()
                page.locator("#reject").click()
                page.wait_for_timeout(80)
                assert "REJECTED" in page.locator("#status").inner_text()
                groups.append("map fit, vehicle selection, waypoint, proposal and reject")

                # Coverage drawing, cancel, clear, valid polygon, spacing, generate/reject.
                page.locator("#coverage-draw").click()
                map_box = page.locator("#map-fallback").bounding_box()
                page.mouse.click(map_box["x"] + map_box["width"] * .50, map_box["y"] + map_box["height"] * .75)
                page.locator("#coverage-clear").click()
                assert page.locator("#coverage-finish").is_disabled()
                page.locator("#coverage-draw").click()
                map_box = page.locator("#map-fallback").bounding_box()
                for x, y in ((50, 15), (80, 15), (80, 35), (50, 35)):
                    page.mouse.click(
                        map_box["x"] + map_box["width"] * x / 100,
                        map_box["y"] + map_box["height"] * (1 - y / 100),
                    )
                assert not page.locator("#coverage-finish").is_disabled()
                page.locator("#coverage-spacing").select_option("60")
                page.locator("#coverage-finish").click()
                page.wait_for_timeout(100)
                assert "PENDING" in page.locator("#status").inner_text()
                page.locator("#reject").click()
                groups.append("coverage draw, cancel/clear, spacing, proposal and reject")

                # Virtual object create, scan, visibility, move and delete.
                page.locator("#test-object-label").fill("Browser test target")
                page.locator("#test-object-category").select_option("marker")
                page.locator("#test-object-difficulty").select_option("easy")
                page.locator("#test-object-visible").check()
                page.locator("#object-place-mode").click()
                map_box = page.locator("#map-fallback").bounding_box()
                page.mouse.click(map_box["x"] + map_box["width"] * .22, map_box["y"] + map_box["height"] * .55)
                page.wait_for_timeout(100)
                assert "Browser test target" in page.locator("#sensor-object-list").inner_text()
                page.locator("#sensor-scan-now").click()
                row = page.locator("[data-object-row]").filter(has_text="Browser test target")
                row.locator("[data-object-toggle]").click()
                page.wait_for_timeout(100)
                row = page.locator("[data-object-row]").filter(has_text="Browser test target")
                assert "hidden" in row.inner_text()
                row.locator("[data-object-toggle]").click()
                page.wait_for_timeout(100)
                row = page.locator("[data-object-row]").filter(has_text="Browser test target")
                row.locator("[data-object-move]").click()
                page.wait_for_timeout(700)  # allow the UI's smooth scroll to the map to settle
                map_box = page.locator("#map-fallback").bounding_box()
                page.mouse.click(map_box["x"] + map_box["width"] * .27, map_box["y"] + map_box["height"] * .50)
                page.wait_for_timeout(140)
                row = page.locator("[data-object-row]").filter(has_text="Browser test target")
                row.locator("[data-object-delete]").click()
                page.wait_for_timeout(80)
                assert page.locator("[data-object-row]").filter(has_text="Browser test target").count() == 0
                page.locator("#sensor-place-object").click()
                assert "PLACE OBJECT" in page.locator("#map-tasking-status").inner_text()
                page.locator("#sensor-place-object").click()
                groups.append("sensor object placement, scan, hide/show, move, delete and both placement buttons")

                # Sensor enable and both range controls.
                sensor_switch = page.locator('[data-sensor-setting="sensor_enabled"][data-vehicle="scout-1"]')
                sensor_switch.uncheck()
                page.wait_for_timeout(60)
                page.locator('[data-sensor-setting="sensor_enabled"][data-vehicle="scout-1"]').check()
                for key, value in (("sensor_range_m", "700"), ("comm_range_m", "1500")):
                    control = page.locator(f'[data-sensor-setting="{key}"][data-vehicle="scout-1"]')
                    control.evaluate(
                        "(element, value) => { element.value = value; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }",
                        value,
                    )
                    page.wait_for_timeout(70)
                groups.append("sensor enable switch and sensor/communication range sliders")

                # Blackbox vehicle selector, refresh, slider, map marker and playback.
                page.wait_for_timeout(1200)  # collect at least two telemetry samples
                page.locator("#blackbox-vehicle").select_option("scout-2")
                page.locator("#blackbox-refresh").click()
                slider = page.locator("#blackbox-replay-slider")
                assert not slider.is_disabled()
                slider.fill(str(max(0, int(slider.get_attribute("max")) - 1)))
                slider.dispatch_event("input")
                page.locator("#blackbox-show-map").click()
                if not page.locator("#blackbox-play").is_disabled():
                    page.locator("#blackbox-play").click()
                    page.wait_for_timeout(450)
                    page.locator("#blackbox-play").click()
                groups.append("blackbox vehicle selector, refresh, scrub, show-on-map, play and pause")

                # Swarm network switches, radio toggles, status, peer test, broadcast,
                # shared-detection proposal, and route-conflict scan.
                page.locator("#swarm-enabled").uncheck()
                page.locator("#swarm-enabled").check()
                page.locator("#swarm-mode").select_option("centralized")
                page.locator("#swarm-peer-mesh").uncheck()
                page.locator("#swarm-central-link").check()
                page.locator("#swarm-save-config").click()
                page.wait_for_timeout(80)
                assert "persisted" in page.locator("#swarm-config-note").inner_text().lower()
                page.locator('[data-radio="scout-2"]').uncheck()
                page.wait_for_timeout(60)
                page.locator('[data-radio="scout-2"]').check()
                page.locator("#swarm-status-request").click()
                page.locator("#swarm-mode").select_option("hybrid")
                page.locator("#swarm-peer-mesh").check()
                page.locator("#swarm-save-config").click()
                page.wait_for_timeout(80)
                page.locator("#peer-test-sender").select_option("scout-1")
                page.locator("#peer-test-recipient").select_option("scout-2")
                page.locator("#swarm-peer-test").click()
                page.locator("#swarm-recipient").select_option("scout-2")
                page.locator("#swarm-broadcast-text").fill("Test informational message")
                page.locator("#swarm-broadcast").click()
                page.locator("#detection-source").select_option("scout-1")
                page.locator("#detection-label").fill("Demo detection")
                page.locator("#detection-x").fill("70")
                page.locator("#detection-y").fill("55")
                page.locator("#detection-confidence").fill("0.9")
                page.locator("#swarm-detection-submit").click()
                page.locator("#swarm-conflict-scan").click()
                page.wait_for_timeout(100)
                groups.append("swarm policy, radios, status, peer test, broadcast, detection and conflict scan")

                # Mission approval, injected outage, recovery proposal, second approval.
                page.locator("#cmd").fill("Send Scout-1 north.")
                page.locator("#plan").click()
                page.wait_for_timeout(120)
                assert "PENDING" in page.locator("#status").inner_text()
                page.locator("#approve").click()
                page.wait_for_timeout(120)
                assert "EXECUTING" in page.locator("#status").inner_text()
                page.locator('[data-fail="scout-1"]').click()
                page.wait_for_timeout(200)
                assert "PENDING" in page.locator("#status").inner_text(), "Expected a recovery proposal"
                assert not page.locator("#approve").is_disabled()
                page.locator("#approve").click()
                page.wait_for_timeout(120)
                assert "EXECUTING" in page.locator("#status").inner_text()
                groups.append("mission generate/approve and failure/recovery/second-approval controls")

                # Refresh and reset, including the confirmation prompt.
                page.locator("#refresh-now").click()
                page.once("dialog", lambda dialog: dialog.accept())
                page.locator("#reset").click()
                page.wait_for_timeout(100)
                assert page.locator("#fleet .vehicle-card").count() == 3
                groups.append("manual refresh and reset confirmation")

                # Small viewport layout sanity; check no document-level horizontal overflow.
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(100)
                dimensions = page.evaluate(
                    "({viewport: document.documentElement.clientWidth, page: document.documentElement.scrollWidth})"
                )
                assert dimensions["page"] <= dimensions["viewport"] + 2, dimensions
                groups.append("mobile viewport horizontal-overflow check")

                browser.close()

    failed_http = [(method, path, status) for method, path, status in api_calls if status >= 400]
    if errors or failed_http:
        raise AssertionError({"browser_errors": errors, "failed_http": failed_http})
    return {
        "interaction_groups_passed": len(groups),
        "interaction_groups": groups,
        "browser_api_calls": len(api_calls),
        "http_status_counts": {str(code): sum(1 for _, _, status in api_calls if status == code)
                                for code in sorted({status for _, _, status in api_calls})},
        "browser_errors": errors,
        "failed_http": failed_http,
    }


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
