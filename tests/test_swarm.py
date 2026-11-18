from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    from backend import db, main
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "swarm-e2e.sqlite3")
    client = TestClient(main.app)
    return client


def test_hybrid_peer_mesh_operates_during_coordinator_link_loss(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        config = client.put("/api/swarm/config", json={
            "coordination_mode": "hybrid", "peer_mesh_enabled": True,
            "coordinator_link_enabled": False,
        })
        assert config.status_code == 200
        peer = client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2",
            "message": "Can you receive this peer packet?",
        })
        assert peer.status_code == 200
        assert peer.json()["status"] == "DELIVERED"
        assert peer.json()["delivered_to"] == ["scout-2"]
        # The operator cannot reach the fleet while the control-station link is down.
        broadcast = client.post("/api/swarm/broadcast", json={"message": "Hold your current sectors."})
        assert broadcast.status_code == 200
        assert broadcast.json()["status"] == "BLOCKED_NO_ROUTE"


def test_centralized_mode_requires_coordinator_relay_for_peer_traffic(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        client.put("/api/swarm/config", json={
            "coordination_mode": "centralized", "peer_mesh_enabled": False,
            "coordinator_link_enabled": False,
        }).raise_for_status()
        peer = client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2",
            "message": "This must not route without the coordinator.",
        })
        assert peer.status_code == 200
        assert peer.json()["status"] == "BLOCKED_NO_ROUTE"


def test_network_pause_and_vehicle_radio_controls(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        client.put("/api/swarm/vehicles/scout-2/radio", json={"enabled": False}).raise_for_status()
        blocked = client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2", "message": "radio test",
        }).json()
        assert blocked["status"] == "BLOCKED_NO_ROUTE"
        client.put("/api/swarm/config", json={"enabled": False}).raise_for_status()
        paused = client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "relay-1", "message": "network pause test",
        }).json()
        assert paused["status"] == "BLOCKED_NETWORK_DISABLED"
        state = client.get("/api/swarm/state").json()
        assert state["connectivity"]["network_status"] == "PAUSED"
        assert state["radios"]["scout-2"] is False


def test_operator_broadcast_and_status_reports(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        broadcast = client.post("/api/swarm/broadcast", json={
            "message": "Keep your current assignments and report changes.",
        }).json()
        assert broadcast["message_type"] == "OPERATOR_ANNOUNCEMENT"
        assert broadcast["payload"]["executable"] is False
        assert set(broadcast["delivered_to"]) == {"scout-1", "scout-2", "relay-1"}
        result = client.post("/api/swarm/status-request")
        assert result.status_code == 200
        assert len(result.json()["reports"]) == 3
        assert all(x["message_type"] == "STATUS_REPORT" for x in result.json()["reports"])


def test_detection_is_shared_and_creates_human_approval_investigation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        response = client.post("/api/swarm/detections", json={
            "source_vehicle_id": "scout-1", "x": 64, "y": 58,
            "label": "Possible vehicle", "confidence": 0.92,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["detection_message"]["message_type"] == "DETECTION_EVENT"
        assert "scout-2" in body["detection_message"]["delivered_to"]
        assert body["task_request"]["message_type"] == "TASK_REQUEST"
        assert body["task_offers"]
        proposal = body["proposal"]
        assert proposal["status"] == "PENDING_APPROVAL"
        assert proposal["actions"][0]["vehicle_id"] == "scout-2"
        before = client.get("/api/state").json()
        scout2 = next(v for v in before["fleet"] if v["id"] == "scout-2")
        assert scout2["status"] == "ready"  # no dispatch before human approval
        approved = client.post(f"/api/missions/{proposal['id']}/approve")
        assert approved.status_code == 200
        after = client.get("/api/state").json()
        scout2 = next(v for v in after["fleet"] if v["id"] == "scout-2")
        assert scout2["status"] == "moving"
        message_types = {m["message_type"] for m in client.get("/api/swarm/state").json()["messages"]}
        assert "INTENT_BROADCAST" in message_types
        assert "ACKNOWLEDGEMENT" in message_types


def test_detection_without_eligible_inspection_peer_does_not_dispatch(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        client.put("/api/swarm/vehicles/scout-2/radio", json={"enabled": False})
        result = client.post("/api/swarm/detections", json={
            "source_vehicle_id": "scout-1", "x": 65, "y": 55,
            "label": "Test target", "confidence": 0.8,
        })
        assert result.status_code == 200
        assert result.json()["proposal"] is None
        assert result.json()["task_offers"] == []


def test_detection_no_go_or_invalid_source_is_rejected(tmp_path, monkeypatch):
    from backend.geospatial import in_no_go_zone
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        rejected = client.post("/api/swarm/detections", json={
            "source_vehicle_id": "scout-1", "x": 30, "y": 70,
            "label": "Restricted test", "confidence": 0.9,
        })
        assert rejected.status_code == 422
        unknown = client.post("/api/swarm/detections", json={
            "source_vehicle_id": "unknown", "x": 60, "y": 55,
        })
        assert unknown.status_code == 404


def test_telemetry_heartbeat_and_acknowledgements_are_published(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        for _ in range(5):
            client.post("/api/simulation/tick").raise_for_status()
        messages = client.get("/api/swarm/state").json()["messages"]
        kinds = {m["message_type"] for m in messages}
        assert {"HEARTBEAT", "POSITION_UPDATE", "BATTERY_UPDATE", "AVAILABILITY_UPDATE"} <= kinds
        assert "ACKNOWLEDGEMENT" in kinds


def test_route_conflict_scan_broadcasts_structured_conflict(tmp_path, monkeypatch):
    from backend import main
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        main.fleet["scout-1"].x=48; main.fleet["scout-1"].y=50
        main.fleet["scout-2"].x=52; main.fleet["scout-2"].y=50
        for vid in ("scout-1","scout-2"):
            main.fleet[vid].max_speed_mps=6; main.fleet[vid].max_accel=100; main.fleet[vid].speed=6
            main.fleet[vid].status="moving"
        main.fleet["scout-1"].target_x = 52; main.fleet["scout-1"].target_y = 50
        main.fleet["scout-2"].target_x = 48; main.fleet["scout-2"].target_y = 50
        result = client.post("/api/swarm/conflicts/check").json()
        assert result["count"] == 1
        messages = client.get("/api/swarm/state").json()["messages"]
        conflict = next(m for m in messages if m["message_type"] == "ROUTE_CONFLICT")
        assert set(conflict["delivered_to"]) == {"scout-1", "scout-2"}


def test_failure_alert_is_broadcast_to_peers(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        client.post("/api/vehicles/scout-1/fail").raise_for_status()
        messages = client.get("/api/swarm/state").json()["messages"]
        alert = next(m for m in messages if m["message_type"] == "EMERGENCY_ALERT")
        assert alert["payload"]["vehicle_id"] == "scout-1"
        assert "scout-2" in alert["delivered_to"]


def test_swarm_configuration_and_messages_persist_in_sqlite(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        client.put("/api/swarm/config", json={"coordination_mode": "centralized", "peer_mesh_enabled": False}).raise_for_status()
        client.put("/api/swarm/vehicles/relay-1/radio", json={"enabled": False}).raise_for_status()
        client.post("/api/swarm/broadcast", json={"message": "Persist this operator broadcast."}).raise_for_status()
    # A second application lifespan restores the persistent swarm snapshot.
    with _client(tmp_path, monkeypatch) as client:
        state = client.get("/api/swarm/state").json()
        assert state["config"]["coordination_mode"] == "centralized"
        assert state["radios"]["relay-1"] is False
        assert any(m["message_type"] == "OPERATOR_ANNOUNCEMENT" for m in state["messages"])


def test_protocol_rejects_unknown_message_type_and_bad_mode():
    from backend.swarm import SwarmNetwork
    import pytest
    from backend.core import demo_fleet
    network = SwarmNetwork(); fleet = demo_fleet(); network.ensure_fleet(fleet)
    with pytest.raises(ValueError, match="allowlisted"):
        network.publish("scout-1", "ARBITRARY_COMMAND", {"cmd": "move"}, ["scout-2"])
    with pytest.raises(ValueError, match="coordination_mode"):
        network.configure({"coordination_mode": "unrestricted"}, fleet)


def test_hybrid_peer_negotiates_task_during_coordinator_link_loss_but_waits_for_human_link(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed")
        client.put("/api/swarm/config", json={
            "coordination_mode": "hybrid", "peer_mesh_enabled": True,
            "coordinator_link_enabled": False,
        }).raise_for_status()
        result = client.post("/api/swarm/detections", json={
            "source_vehicle_id": "scout-1", "x": 66, "y": 56,
            "label": "Peer-only test anomaly", "confidence": 0.91,
        })
        assert result.status_code == 200, result.text
        proposal = result.json()["proposal"]
        assert proposal["status"] == "PENDING_APPROVAL"
        assert proposal["coordination_mode"] == "peer-negotiated"
        offer = result.json()["task_offers"][0]
        assert offer["sender"] == "scout-2"
        assert offer["delivered_to"] == ["scout-1"]
        # Peer negotiation shares information only; mission dispatch is blocked without operator link.
        refused = client.post(f"/api/missions/{proposal['id']}/approve")
        assert refused.status_code == 409
        assert client.get("/api/state").json()["fleet"][1]["status"] == "ready"
        client.put("/api/swarm/config", json={"coordinator_link_enabled": True}).raise_for_status()
        approved = client.post(f"/api/missions/{proposal['id']}/approve")
        assert approved.status_code == 200
        assert client.get("/api/state").json()["fleet"][1]["status"] == "moving"


def test_peer_mesh_enforces_configured_radio_range(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        client.put("/api/swarm/config", json={
            "coordination_mode": "hybrid", "peer_mesh_enabled": True,
            "coordinator_link_enabled": False,
        }).raise_for_status()
        # The seeded Scouts are about 949 m apart; a 100 m symmetric link must fail.
        for vehicle in ("scout-1", "scout-2"):
            client.put(f"/api/sensors/vehicles/{vehicle}", json={"comm_range_m": 100}).raise_for_status()
        blocked = client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2", "message": "Out of range",
        }).json()
        assert blocked["status"] == "BLOCKED_NO_ROUTE"
        # Extending both ends beyond separation restores the peer link.
        for vehicle in ("scout-1", "scout-2"):
            client.put(f"/api/sensors/vehicles/{vehicle}", json={"comm_range_m": 1100}).raise_for_status()
        delivered = client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2", "message": "In range",
        }).json()
        assert delivered["status"] == "DELIVERED"


def test_shared_fleet_picture_does_not_omnisciently_update_radio_off_vehicle(tmp_path, monkeypatch):
    from backend import main
    with _client(tmp_path, monkeypatch) as client:
        client.post('/api/fleet/seed').raise_for_status()
        client.put('/api/swarm/vehicles/scout-1/radio', json={'enabled':False}).raise_for_status()
        main.fleet['scout-1'].x=33.0
        main.fleet['scout-1'].y=44.0
        for _ in range(5): client.post('/api/simulation/tick').raise_for_status()
        knowledge=client.get('/api/swarm/state').json()['knowledge']['vehicles']['scout-1']
        assert knowledge.get('x') != 33.0
        client.put('/api/swarm/vehicles/scout-1/radio', json={'enabled':True}).raise_for_status()
        for _ in range(5): client.post('/api/simulation/tick').raise_for_status()
        knowledge=client.get('/api/swarm/state').json()['knowledge']['vehicles']['scout-1']
        assert knowledge['x'] == 33.0 and knowledge['y'] == 44.0


def test_time_aware_conflict_scan_does_not_flag_geometric_crossing_at_different_times(tmp_path, monkeypatch):
    from backend import main
    with _client(tmp_path, monkeypatch) as client:
        client.post('/api/fleet/seed')
        a=main.fleet['scout-1']; b=main.fleet['scout-2']
        a.x,a.y=10,20; a.target_x,a.target_y=30,20; a.max_speed_mps=20; a.speed=20; a.max_accel=100; a.status='moving'
        b.x,b.y=20,10; b.target_x,b.target_y=20,30; b.max_speed_mps=2; b.speed=2; b.max_accel=0.1; b.status='moving'
        result=client.post('/api/swarm/conflicts/check').json()
        assert result['count']==0


def test_recipient_specific_vehicle_knowledge_is_not_globally_shared():
    from backend.swarm import SwarmNetwork
    from backend.core import demo_fleet
    fleet=demo_fleet(); network=SwarmNetwork(); network.ensure_fleet(fleet)
    network.update_link_geometry(fleet, {'scout-1':{'comm_range_m':1500},'scout-2':{'comm_range_m':1500}})
    network.configure({'coordinator_link_enabled':False},fleet)
    message=network.publish('scout-1','HEARTBEAT',{'x':18,'y':25,'status':'ready','battery_pct':90},['scout-2'])
    assert message['status']=='DELIVERED'
    assert network.knowledge['by_recipient']['scout-2']['scout-1']['x']==18
    assert network.knowledge['vehicles']['scout-1']=={}


def test_network_latency_queues_then_delivers_after_configured_ticks():
    from backend.swarm import SwarmNetwork
    from backend.core import demo_fleet
    fleet=demo_fleet(); network=SwarmNetwork(); network.ensure_fleet(fleet)
    network.update_link_geometry(fleet, {'scout-1':{'comm_range_m':1500},'scout-2':{'comm_range_m':1500}})
    network.configure({'network_latency_ticks':2},fleet)
    message=network.publish('scout-1','PEER_TEST',{'text':'delayed'},['scout-2'])
    assert message['status']=='QUEUED' and message['delivered_to']==[]
    network.advance_network(fleet)
    assert message['status']=='QUEUED'
    network.advance_network(fleet)
    assert message['status']=='DELIVERED' and message['delivered_to']==['scout-2']


def test_packet_loss_is_deterministically_applied():
    from backend.swarm import SwarmNetwork
    from backend.core import demo_fleet
    fleet=demo_fleet(); network=SwarmNetwork(); network.ensure_fleet(fleet)
    network.update_link_geometry(fleet, {'scout-1':{'comm_range_m':1500},'scout-2':{'comm_range_m':1500}})
    network.configure({'packet_loss_pct':100.0},fleet)
    message=network.publish('scout-1','PEER_TEST',{'text':'lost'},['scout-2'])
    assert message['status']=='BLOCKED_PACKET_LOSS'
    assert message['dropped_to']==['scout-2']


def test_network_config_api_latency_and_packet_loss(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post('/api/fleet/seed').raise_for_status()
        config=client.put('/api/swarm/config',json={'network_latency_ticks':2,'packet_loss_pct':0}).json()
        assert config['config']['network_latency_ticks']==2
        queued=client.post('/api/swarm/peer-test',json={'sender_vehicle_id':'scout-1','recipient_vehicle_id':'scout-2','message':'latency'}).json()
        assert queued['status']=='QUEUED'
        client.post('/api/simulation/tick').raise_for_status()
        client.post('/api/simulation/tick').raise_for_status()
        messages=client.get('/api/swarm/state').json()['messages']
        delivered=next(m for m in messages if m['id']==queued['id'])
        assert delivered['status']=='DELIVERED' and delivered['delivered_to']==['scout-2']
        client.put('/api/swarm/config',json={'network_latency_ticks':0,'packet_loss_pct':100}).raise_for_status()
        dropped=client.post('/api/swarm/peer-test',json={'sender_vehicle_id':'scout-1','recipient_vehicle_id':'scout-2','message':'loss'}).json()
        assert dropped['status']=='BLOCKED_PACKET_LOSS'


def test_delayed_peer_message_generates_ack_only_after_delivery():
    from backend.swarm import SwarmNetwork
    from backend.core import demo_fleet
    fleet=demo_fleet(); network=SwarmNetwork(); network.ensure_fleet(fleet)
    network.update_link_geometry(fleet,{'scout-1':{'comm_range_m':1500},'scout-2':{'comm_range_m':1500}})
    network.configure({'network_latency_ticks':2},fleet)
    message=network.publish('scout-1','PEER_TEST',{'text':'delayed ack'},['scout-2'])
    assert message['status']=='QUEUED'
    network.advance_network(fleet)
    assert not any(m['message_type']=='ACKNOWLEDGEMENT' for m in network.messages)
    network.advance_network(fleet)
    assert message['status']=='DELIVERED'
    ack=next(m for m in network.messages if m['message_type']=='ACKNOWLEDGEMENT')
    assert ack['sender']=='scout-2' and ack['recipients']==['scout-1']
    assert ack['status']=='QUEUED'
    assert len(network.pending_delivery)==1
    network.advance_network(fleet)
    assert ack['status']=='QUEUED'
    network.advance_network(fleet)
    assert ack['status']=='DELIVERED' and ack['delivered_to']==['scout-1']


def test_delayed_sensor_coordination_completes_end_to_end(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'latency-coordination.sqlite3')
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed').raise_for_status()
        client.put('/api/swarm/config',json={'network_latency_ticks':2,'packet_loss_pct':0}).raise_for_status()
        for vehicle in ('scout-1','scout-2'):
            client.put(f'/api/sensors/vehicles/{vehicle}',json={'sensor_range_m':700}).raise_for_status()
        created=client.post('/api/sensors/objects',json={
            'x':22,'y':45,'label':'Delayed coordination target','category':'marker',
            'difficulty':'easy','visible':True})
        assert created.status_code==200,created.text
        scan=client.post('/api/sensors/scan')
        assert scan.status_code==200,scan.text
        assert scan.json()['automated_proposals']==[]
        assert client.get('/api/swarm/state').json()['pending_coordination']==1
        proposal=None
        for _ in range(12):
            client.post('/api/simulation/tick').raise_for_status()
            missions=client.get('/api/state').json()['missions']
            proposal=next((m for m in missions if m.get('provider')=='swarm-detection-coordination'),None)
            if proposal:
                break
        assert proposal and proposal['status']=='PENDING_APPROVAL'
        assert proposal['actions'][0]['vehicle_id'] in ('scout-1','scout-2','relay-1')
        assert client.get('/api/swarm/state').json()['pending_coordination']==0
        messages=client.get('/api/swarm/state').json()['messages']
        assert any(m['message_type']=='TASK_REQUEST' and m['status']=='DELIVERED' for m in messages)
        assert any(m['message_type']=='TASK_OFFER' and m['status']=='DELIVERED' for m in messages)
