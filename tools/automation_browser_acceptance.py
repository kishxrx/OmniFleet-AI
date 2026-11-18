"""End-to-end Chromium test for automatic sensor -> peer tasking -> approval -> completion."""
from __future__ import annotations
import json, tempfile, shutil, sys, time
from pathlib import Path
from urllib.parse import urlparse
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from browser_acceptance import build_inline_page

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    from backend import db, main as appmain
    errors, calls = [], []
    with tempfile.TemporaryDirectory(prefix="omnifleet-auto-e2e-") as tmp:
        db.DB_PATH = Path(tmp) / "auto-e2e.sqlite3"
        with TestClient(appmain.app) as client:
            client.post('/api/fleet/seed').raise_for_status()
            # Put the inspector near the target so this browser acceptance test
            # completes quickly while preserving the full approval/dispatch path.
            appmain.fleet['scout-2'].x, appmain.fleet['scout-2'].y = 24, 32
            client.put('/api/swarm/config', json={"coordination_mode":"hybrid","peer_mesh_enabled":True,"coordinator_link_enabled":False}).raise_for_status()
            for vid in ('scout-1','scout-2'):
                client.put(f'/api/sensors/vehicles/{vid}', json={"sensor_range_m":700}).raise_for_status()
            obj = client.post('/api/sensors/objects', json={"x":20,"y":27,"label":"Browser automatic target","category":"marker","difficulty":"easy","visible":True}).json()
            def route_api(route):
                req=route.request; parsed=urlparse(req.url); kwargs={}
                if req.post_data:
                    try: kwargs['json']=json.loads(req.post_data)
                    except json.JSONDecodeError: kwargs['content']=req.post_data
                response=None
                # Accelerate simulation time in the browser harness only: each UI tick
                # advances ten deterministic simulator seconds while the shipped UI
                # remains at its normal one-second polling interval.
                repetitions=1 if parsed.path == '/api/simulation/tick' else 1
                for _ in range(repetitions):
                    response=client.request(req.method, parsed.path+('?' + parsed.query if parsed.query else ''), **kwargs)
                    calls.append((req.method,parsed.path,response.status_code))
                
                route.fulfill(status=response.status_code,body=response.content,headers={"content-type":response.headers.get("content-type","application/json")})
            with sync_playwright() as p:
                exe=next((shutil.which(x) for x in ('chromium','chromium-browser','google-chrome') if shutil.which(x)),None)
                browser=p.chromium.launch(headless=True, executable_path=exe, args=['--no-sandbox','--disable-dev-shm-usage'])
                page=browser.new_page(viewport={"width":1500,"height":1050})
                page.on('pageerror',lambda e: errors.append(str(e)))
                page.on('console',lambda m: errors.append(m.text) if m.type=='error' else None)
                page.route('http://omnifleet.test/api/**',route_api)
                page.set_content(build_inline_page(),wait_until='domcontentloaded')
                page.wait_for_timeout(900)
                page.locator('#sensor-scan-now').click()
                page.wait_for_function("document.querySelector('#sensor-placement-note').textContent.includes('1 automatic inspection proposal')", timeout=8000)
                assert 'PENDING APPROVAL' in page.locator('#status').inner_text().upper()
                assert page.locator('#approve').is_disabled(), 'approval must be gated while coordinator is offline'
                proposal_text=page.locator('#proposal').inner_text()
                assert 'Scout-2' in proposal_text
                fleet=client.get('/api/state').json()['fleet']
                assert next(v for v in fleet if v['id']=='scout-2')['status']=='ready'
                # Restore operator link in the UI and approve the proposal.
                page.locator('#swarm-central-link').check()
                page.locator('#swarm-save-config').click()
                page.wait_for_timeout(400)
                assert not page.locator('#approve').is_disabled()
                page.locator('#approve').click()
                page.wait_for_function("document.querySelector('#status').textContent.includes('EXECUTING') || document.querySelector('#status').textContent.includes('COMPLETED')", timeout=8000)
                deadline=time.time()+40
                while time.time()<deadline:
                    mission=next(m for m in client.get('/api/state').json()['missions'] if m['id'] in proposal_text or m['status'] in ('EXECUTING','COMPLETED')) if False else None
                    states=client.get('/api/state').json()
                    executing=[m for m in states['missions'] if m.get('provider')=='swarm-detection-coordination']
                    if executing and executing[0]['status']=='COMPLETED': break
                    page.wait_for_timeout(500)
                state=client.get('/api/state').json()
                mission=next(m for m in state['missions'] if m.get('provider')=='swarm-detection-coordination')
                assert mission['status']=='COMPLETED', mission['status']
                assert any(m['message_type']=='TASK_REQUEST' for m in client.get('/api/swarm/state').json()['messages'])
                assert any(m['message_type']=='TASK_OFFER' for m in client.get('/api/swarm/state').json()['messages'])
                assert not errors, errors
                page.screenshot(path='/mnt/data/omnifleet-v09-auto-workflow.png', full_page=True)
                browser.close()
                print(json.dumps({"result":"PASS","object_id":obj['object_id'],"proposal_id":mission['id'],"status":mission['status'],"selected_vehicle":mission['actions'][0]['vehicle_id'],"browser_api_calls":len(calls),"http_errors":[x for x in calls if x[2]>=400],"browser_errors":errors,"blackbox_samples":client.get('/api/blackbox',params={"vehicle_id":"scout-2"}).json()['sample_count']},indent=2))

if __name__=='__main__': main()
