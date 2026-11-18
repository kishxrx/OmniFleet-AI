from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    from backend import db, main
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "omnifleet-sensors.sqlite3")
    return TestClient(main.app)


def test_virtual_object_detected_by_two_vehicles_and_shared_over_swarm(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        created = client.post("/api/sensors/objects", json={
            "x": 22, "y": 45, "label": "Test Object A", "category": "marker",
            "difficulty": "easy", "visible": True,
        })
        assert created.status_code == 200, created.text
        object_id = created.json()["object_id"]

        scan = client.post("/api/sensors/scan")
        assert scan.status_code == 200, scan.text
        result = scan.json()
        assert result["count"] == 2
        assert {x["source_vehicle_id"] for x in result["new_observations"]} == {"scout-1", "scout-2"}
        assert all(x["shared_status"] == "SHARED" for x in result["new_observations"])
        state = client.get("/api/sensors/state").json()
        obj = next(x for x in state["objects"] if x["object_id"] == object_id)
        assert obj["information_status"] == "CORROBORATED"
        assert obj["observation_count"] == 2
        messages = client.get("/api/swarm/state").json()["messages"]
        assert any(x["message_type"] == "SENSOR_OBSERVATION" for x in messages)


def test_hidden_object_is_not_observed_until_shown_and_revision_rescanned(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        obj = client.post("/api/sensors/objects", json={
            "x": 18, "y": 25, "label": "Hidden marker", "category": "marker",
            "difficulty": "easy", "visible": False,
        }).json()
        assert client.post("/api/sensors/scan").json()["count"] == 0
        shown = client.put(f"/api/sensors/objects/{obj['object_id']}", json={"visible": True})
        assert shown.status_code == 200
        assert shown.json()["revision"] == 2
        assert client.post("/api/sensors/scan").json()["count"] == 1
        moved = client.put(f"/api/sensors/objects/{obj['object_id']}", json={"x": 19, "y": 26})
        assert moved.status_code == 200
        assert moved.json()["revision"] == 3
        assert client.post("/api/sensors/scan").json()["count"] == 1


def test_object_validation_blocks_no_go_and_outside_geofence(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        no_go = client.post("/api/sensors/objects", json={
            "x": 30, "y": 70, "label": "Restricted marker", "category": "marker",
        })
        assert no_go.status_code == 422
        outside = client.post("/api/sensors/objects", json={
            "x": 2, "y": 50, "label": "Outside marker", "category": "marker",
        })
        assert outside.status_code == 422


def test_radio_off_keeps_local_observation_but_blocks_sharing(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        client.put("/api/swarm/vehicles/scout-1/radio", json={"enabled": False}).raise_for_status()
        obj = client.post("/api/sensors/objects", json={
            "x": 18, "y": 25, "label": "Local-only marker", "category": "marker",
            "difficulty": "easy",
        }).json()
        scan = client.post("/api/sensors/scan").json()
        own = [o for o in scan["new_observations"] if o["source_vehicle_id"] == "scout-1"]
        assert len(own) == 1
        assert own[0]["shared_status"] == "LOCAL_ONLY"
        assert own[0]["delivered_to"] == []
        state = client.get("/api/sensors/state").json()
        assert any(o["object_id"] == obj["object_id"] for o in state["objects"])


def test_sensor_configuration_bounds_and_settings_persist(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        bad = client.put("/api/sensors/vehicles/scout-1", json={"sensor_range_m": 5000})
        assert bad.status_code == 422
        changed = client.put("/api/sensors/vehicles/scout-1", json={
            "sensor_enabled": False, "sensor_range_m": 700, "comm_range_m": 1500,
        })
        assert changed.status_code == 200
        state = client.get("/api/sensors/state").json()
        assert state["settings"]["scout-1"] == {
            "sensor_enabled": False, "sensor_range_m": 700.0, "comm_range_m": 1500.0,
        }


def test_blackbox_telemetry_events_and_replay_data(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        client.post("/api/simulation/tick").raise_for_status()
        obj = client.post("/api/sensors/objects", json={
            "x": 18, "y": 25, "label": "Blackbox marker", "category": "marker",
            "difficulty": "easy",
        }).json()
        client.post("/api/sensors/scan").raise_for_status()
        data = client.get("/api/blackbox?vehicle_id=scout-1&limit=20")
        assert data.status_code == 200
        payload = data.json()
        assert payload["sample_count"] >= 2
        assert len(payload["samples"]) >= 2
        assert {"speed_mps", "battery_pct", "heading_deg", "sensor_range_m", "radio_enabled"} <= set(payload["samples"][-1])
        assert any(e["event_type"] == "SENSOR_OBSERVATION" for e in payload["events"])
        assert client.get("/api/blackbox?vehicle_id=does-not-exist").status_code == 404
        assert client.get("/api/blackbox?limit=501").status_code == 422


def test_sensor_objects_and_blackbox_survive_restart(tmp_path, monkeypatch):
    from backend import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "persist-sensors.sqlite3")
    from backend.main import app
    with TestClient(app) as first:
        first.post("/api/fleet/seed").raise_for_status()
        obj = first.post("/api/sensors/objects", json={
            "x": 18, "y": 25, "label": "Persistent marker", "category": "marker",
            "difficulty": "easy",
        }).json()
        first.post("/api/sensors/scan").raise_for_status()
        first.post("/api/simulation/tick").raise_for_status()
    with TestClient(app) as second:
        state = second.get("/api/sensors/state").json()
        assert any(x["object_id"] == obj["object_id"] for x in state["objects"])
        assert len(second.get("/api/blackbox?vehicle_id=scout-1").json()["samples"]) >= 2


def test_sensor_scan_runs_automatically_on_simulation_ticks_and_peer_mesh_shares_during_coordinator_outage(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        client.put("/api/swarm/config", json={
            "coordination_mode": "hybrid", "peer_mesh_enabled": True,
            "coordinator_link_enabled": False,
        }).raise_for_status()
        client.post("/api/sensors/objects", json={
            "x": 22, "y": 45, "label": "Tick-detected marker", "category": "marker",
            "difficulty": "easy", "visible": True,
        }).raise_for_status()
        tick = client.post("/api/simulation/tick")
        assert tick.status_code == 200
        state = client.get("/api/sensors/state").json()
        assert len(state["observations"]) == 2
        assert all(x["shared_status"] == "SHARED" for x in state["observations"])


def test_deleted_objects_disappear_but_blackbox_keeps_the_event_history(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        obj = client.post("/api/sensors/objects", json={
            "x": 18, "y": 25, "label": "Removable marker", "category": "marker",
        }).json()
        client.delete(f"/api/sensors/objects/{obj['object_id']}").raise_for_status()
        state = client.get("/api/sensors/state").json()
        assert all(x["object_id"] != obj["object_id"] for x in state["objects"])
        blackbox = client.get("/api/blackbox/events?limit=50").json()["events"]
        assert any(e["event_type"] == "TEST_OBJECT_CREATED" for e in blackbox)
        assert any(e["event_type"] == "TEST_OBJECT_REMOVED" for e in blackbox)


def test_sensor_scan_automatically_creates_inspection_proposal_but_never_dispatches(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        for vehicle in ("scout-1", "scout-2"):
            client.put(f"/api/sensors/vehicles/{vehicle}", json={"sensor_range_m": 700}).raise_for_status()
        obj = client.post("/api/sensors/objects", json={
            "x": 22, "y": 45, "label": "Automatic inspection marker", "category": "marker",
            "difficulty": "easy", "visible": True,
        }).json()
        scan = client.post("/api/sensors/scan")
        assert scan.status_code == 200, scan.text
        body = scan.json()
        assert len(body["new_observations"]) >= 2
        assert len(body["automated_proposals"]) == 1
        proposal = body["automated_proposals"][0]["proposal"]
        assert proposal["status"] == "PENDING_APPROVAL"
        assert proposal["actions"][0]["vehicle_id"] == "scout-2"
        fleet = client.get("/api/state").json()["fleet"]
        assert next(v for v in fleet if v["id"] == "scout-2")["status"] == "ready"
        # Same object revision must not create duplicate proposals on another scan/tick.
        again = client.post("/api/sensors/scan").json()
        assert again["automated_proposals"] == []
        assert client.get("/api/sensors/automation").json()["min_sources"] == 2
        assert obj["object_id"]


def test_delayed_observation_corroboration_uses_full_history(tmp_path, monkeypatch):
    from backend import main
    with _client(tmp_path, monkeypatch) as client:
        client.post('/api/fleet/seed').raise_for_status()
        client.put('/api/sensors/vehicles/scout-2', json={'sensor_enabled':False}).raise_for_status()
        for vid in ('scout-1','scout-2'):
            client.put(f'/api/sensors/vehicles/{vid}', json={'sensor_range_m':700}).raise_for_status()
        client.put('/api/sensors/vehicles/scout-2', json={'sensor_enabled':False}).raise_for_status()
        client.post('/api/sensors/objects', json={'x':22,'y':45,'label':'Delayed corroboration','category':'marker','difficulty':'easy'}).raise_for_status()
        first=client.post('/api/sensors/scan').json()
        assert {o['source_vehicle_id'] for o in first['new_observations']} == {'scout-1'}
        client.put('/api/sensors/vehicles/scout-2', json={'sensor_enabled':True}).raise_for_status()
        second=client.post('/api/sensors/scan').json()
        assert {o['source_vehicle_id'] for o in second['new_observations']} == {'scout-2'}
        assert len(second['automated_proposals']) == 1
        assert second['automated_proposals'][0]['proposal']['status'] == 'PENDING_APPROVAL'


def test_automation_retries_after_no_source_radio_then_recovers(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post('/api/fleet/seed').raise_for_status()
        for vid in ('scout-1','scout-2'):
            client.put(f'/api/sensors/vehicles/{vid}', json={'sensor_range_m':700}).raise_for_status()
            client.put(f'/api/swarm/vehicles/{vid}/radio', json={'enabled':False}).raise_for_status()
        client.post('/api/sensors/objects', json={'x':22,'y':45,'label':'Retry marker','category':'marker','difficulty':'easy'}).raise_for_status()
        first=client.post('/api/sensors/scan').json()
        assert first['automated_proposals'] == []
        client.put('/api/swarm/vehicles/scout-1/radio', json={'enabled':True}).raise_for_status()
        client.put('/api/swarm/vehicles/scout-2/radio', json={'enabled':True}).raise_for_status()
        # Advance enough ticks for the retry backoff while retaining observations.
        for _ in range(4):
            result=client.post('/api/simulation/tick')
            assert result.status_code == 200, result.text
        missions=client.get('/api/state').json()['missions']
        assert any(m.get('provider') == 'swarm-detection-coordination' and m['status']=='PENDING_APPROVAL' for m in missions)


def test_low_battery_creates_operator_approved_return_home_proposal(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post('/api/fleet/seed').raise_for_status()
        from backend.main import fleet
        fleet['scout-1'].battery_pct=19.5
        client.post('/api/simulation/tick').raise_for_status()
        missions=client.get('/api/state').json()['missions']
        recovery=next(m for m in missions if m.get('provider')=='deterministic-battery-recovery')
        assert recovery['status']=='PENDING_APPROVAL'
        assert recovery['actions'][0]['action']=='return_home'
        approved=client.post(f"/api/missions/{recovery['id']}/approve")
        assert approved.status_code==200, approved.text
        assert fleet['scout-1'].status=='returning'
