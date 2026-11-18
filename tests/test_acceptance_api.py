"""High-level HTTP contract and workflow acceptance tests for the complete v0.7 app."""
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    from backend import db, main
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "acceptance.sqlite3")
    return TestClient(main.app)


def test_public_pages_and_all_read_endpoints(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/").status_code == 200
        assert "OmniFleet AI" in client.get("/").text
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/api/health").json()["version"] == "0.9.2"
        assert client.get("/api/state").status_code == 200
        assert client.get("/api/events").status_code == 200
        assert client.get("/api/map/config").json()["width_m"] == 2000
        assert client.get("/api/swarm/state").status_code == 200
        assert client.get("/api/sensors/state").status_code == 200
        assert client.get("/api/blackbox").status_code == 200
        assert client.get("/api/blackbox/events").status_code == 200


def test_operator_workflows_cover_missions_map_coverage_sensors_swarm_and_blackbox(tmp_path, monkeypatch):
    from backend.geospatial import local_to_wgs84

    with _client(tmp_path, monkeypatch) as client:
        assert client.post("/api/fleet/seed").status_code == 200

        # Natural-language mission: proposal -> explicit rejection.
        proposal = client.post("/api/plan", json={
            "instruction": "Send Scout-1 north and Scout-2 east. Keep Relay-1 stationary."
        })
        assert proposal.status_code == 200
        mission = proposal.json()
        assert mission["status"] == "PENDING_APPROVAL"
        assert client.post(f"/api/missions/{mission['id']}/reject").json()["status"] == "REJECTED"

        # Map waypoint: geographic conversion -> approval -> simulation tick.
        cfg = client.get("/api/map/config").json()
        waypoint = client.post("/api/map/waypoint", json={
            "vehicle_id": "scout-1", "latitude": cfg["origin"]["lat"], "longitude": cfg["origin"]["lon"]
        })
        assert waypoint.status_code == 200
        waypoint_mission = waypoint.json()
        assert client.post(f"/api/missions/{waypoint_mission['id']}/approve").status_code == 200
        assert client.post("/api/simulation/tick").status_code == 200

        # Coverage planning: geographic polygon -> sector proposal -> reject.
        polygon = [
            {"latitude": local_to_wgs84(50, 40)[0], "longitude": local_to_wgs84(50, 40)[1]},
            {"latitude": local_to_wgs84(80, 40)[0], "longitude": local_to_wgs84(80, 40)[1]},
            {"latitude": local_to_wgs84(80, 58)[0], "longitude": local_to_wgs84(80, 58)[1]},
            {"latitude": local_to_wgs84(50, 58)[0], "longitude": local_to_wgs84(50, 58)[1]},
        ]
        coverage = client.post("/api/missions/coverage/plan", json={"polygon": polygon, "lane_spacing_m": 60})
        assert coverage.status_code == 200, coverage.text
        assert coverage.json()["status"] == "PENDING_APPROVAL"
        assert coverage.json()["coverage_summary"]["sector_count"] >= 1
        assert client.post(f"/api/missions/{coverage.json()['id']}/reject").status_code == 200

        # Sensor object CRUD, manual scan, vehicle configuration and blackbox read.
        created = client.post("/api/sensors/objects", json={
            "x": 22, "y": 45, "label": "Acceptance target", "category": "marker",
            "difficulty": "easy", "visible": True,
        })
        assert created.status_code == 200
        object_id = created.json()["object_id"]
        scan = client.post("/api/sensors/scan")
        assert scan.status_code == 200 and scan.json()["count"] >= 1
        assert client.put(f"/api/sensors/objects/{object_id}", json={"visible": False}).status_code == 200
        assert client.put(f"/api/sensors/objects/{object_id}", json={"visible": True, "x": 23, "y": 46}).status_code == 200
        assert client.put("/api/sensors/vehicles/scout-1", json={
            "sensor_enabled": True, "sensor_range_m": 700, "comm_range_m": 1500
        }).status_code == 200
        assert client.get("/api/blackbox?vehicle_id=scout-1&limit=20").status_code == 200
        assert client.get("/api/blackbox/events?vehicle_id=scout-1&limit=20").status_code == 200
        assert client.delete(f"/api/sensors/objects/{object_id}").json()["deleted"] is True

        # Swarm controls: config, radio, peer link, status reports, broadcast, detection and conflict scan.
        config = client.put("/api/swarm/config", json={
            "enabled": True, "coordination_mode": "hybrid", "peer_mesh_enabled": True,
            "coordinator_link_enabled": True,
        })
        assert config.status_code == 200
        assert client.put("/api/swarm/vehicles/relay-1/radio", json={"enabled": False}).status_code == 200
        assert client.put("/api/swarm/vehicles/relay-1/radio", json={"enabled": True}).status_code == 200
        assert client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2", "message": "Acceptance peer test"
        }).status_code == 200
        assert client.post("/api/swarm/status-request").status_code == 200
        assert client.post("/api/swarm/broadcast", json={"message": "Acceptance broadcast"}).status_code == 200
        detection = client.post("/api/swarm/detections", json={
            "source_vehicle_id": "scout-1", "x": 70, "y": 55,
            "label": "Acceptance observation", "confidence": 0.9,
        })
        assert detection.status_code == 200
        assert detection.json()["detection"]["label"] == "Acceptance observation"
        assert detection.json()["proposal"]["status"] == "PENDING_APPROVAL"
        assert client.post("/api/swarm/conflicts/check").status_code == 200

        # A controlled failure of a vehicle with an active waypoint degrades its mission.
        failure = client.post("/api/vehicles/scout-1/fail")
        assert failure.status_code == 200
        assert waypoint_mission["id"] in failure.json()["degraded_missions"]
        recovery = failure.json()["recovery_proposals"]
        assert recovery and recovery[0]["status"] in ("PENDING_APPROVAL", "RECOVERY_UNAVAILABLE")
        # The operator reset control must return the full demo fleet and clean sensor state.
        reset = client.post("/api/fleet/seed")
        assert reset.status_code == 200
        assert reset.json()["summary"]["vehicles_total"] == 3
        assert client.get("/api/sensors/state").json()["summary"]["active_objects"] == 0


def test_validation_and_missing_resource_responses_are_deliberate(tmp_path, monkeypatch):
    from backend.geospatial import local_to_wgs84

    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/fleet/seed").raise_for_status()
        assert client.post("/api/plan", json={"instruction": "x"}).status_code == 422
        assert client.post("/api/plan", json={"instruction": "x" * 1201}).status_code == 422
        assert client.post("/api/map/waypoint", json={
            "vehicle_id": "ghost", "latitude": 12.9716, "longitude": 77.5946
        }).status_code == 404
        lat, lon = local_to_wgs84(30, 70)
        assert client.post("/api/map/waypoint", json={
            "vehicle_id": "scout-1", "latitude": lat, "longitude": lon
        }).status_code == 422  # restricted no-go polygon
        assert client.post("/api/sensors/objects", json={
            "x": 101, "y": 50, "label": "Bad coordinate", "category": "marker"
        }).status_code == 422
        assert client.put("/api/sensors/objects/not-found", json={"visible": False}).status_code == 404
        assert client.delete("/api/sensors/objects/not-found").status_code == 404
        assert client.put("/api/sensors/vehicles/ghost", json={"sensor_enabled": False}).status_code == 404
        assert client.put("/api/swarm/vehicles/ghost/radio", json={"enabled": False}).status_code == 404
        assert client.get("/api/blackbox?vehicle_id=ghost").status_code == 404
        assert client.post("/api/swarm/peer-test", json={
            "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-1", "message": "Self link"
        }).status_code == 422
        assert client.post("/api/swarm/broadcast", json={
            "message": "Unknown recipient", "recipients": ["ghost"]
        }).status_code == 404
        assert client.post("/api/vehicles/ghost/fail").status_code == 404
        assert client.post("/api/missions/not-found/approve").status_code == 404
        assert client.post("/api/missions/not-found/reject").status_code == 404
