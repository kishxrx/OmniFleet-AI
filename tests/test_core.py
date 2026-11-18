from backend.core import demo_fleet,tick
from backend.agents import offline_plan

def test_heterogeneous_fleet():
    f=demo_fleet(); assert len(f)==3 and len({v.kind for v in f.values()})==3

def test_offline_multi_vehicle_proposal():
    f=[v.public() for v in demo_fleet().values()]
    a=offline_plan("Send Scout-1 north and Scout-2 east",f)
    assert {x["vehicle_id"] for x in a}=={"scout-1","scout-2"}

def test_sim_moves_toward_waypoint():
    f=demo_fleet(); v=f["scout-1"]; v.target_x=50;v.target_y=25;v.status="moving";old=v.x
    tick(f);assert v.x>old


def test_offline_plan_keeps_per_vehicle_intent_separate():
    f=[v.public() for v in demo_fleet().values()]
    a=offline_plan("Send Scout-1 north and Scout-2 east. Keep Relay-1 stationary.",f)
    by={x["vehicle_id"]:x["action"] for x in a}
    assert by=={"scout-1":"goto","scout-2":"goto","relay-1":"hold"}


def test_empty_plan_is_not_approvable():
    import asyncio
    import backend.agents as agents
    async def fake_planner(text, fleet): return [], "test"
    original = agents.planner
    agents.planner = fake_planner
    try:
        mission = asyncio.run(agents.AgentOrchestrator().plan("do nothing", demo_fleet(), []))
        assert mission["status"] == "REJECTED"
        assert "Planner returned no executable actions" in mission["checks"]
    finally:
        agents.planner = original

def test_acceleration_and_battery_dynamics():
    f=demo_fleet(); v=f['scout-1']; v.target_x=80; v.target_y=25; v.status='moving'
    before=v.battery_pct; tick(f,1.0)
    assert 0 < v.x < 80
    assert 0 < v.speed <= v.max_speed_mps
    assert v.battery_pct < before


def test_sqlite_snapshot_round_trip(tmp_path, monkeypatch):
    from backend import db
    from backend.core import demo_fleet, vehicle_from_dict
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'state.sqlite3')
    fleet=demo_fleet(); missions=[{'id':'m1','status':'COMPLETED'}]; events=[{'agent':'test','message':'persisted'}]
    db.save_snapshot(fleet,missions,events)
    restored=db.load_snapshot()
    assert restored['missions']==missions
    assert restored['events']==events
    assert vehicle_from_dict(restored['fleet']['scout-1']).name=='Scout-1'


def test_failure_recovery_api_end_to_end(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'e2e.sqlite3')
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed')
        plan=client.post('/api/plan',json={'instruction':'Send Scout-1 north.'}).json()
        assert plan['status']=='PENDING_APPROVAL'
        approved=client.post(f"/api/missions/{plan['id']}/approve")
        assert approved.status_code==200
        failed=client.post('/api/vehicles/scout-1/fail').json()
        assert failed['degraded_missions']==[plan['id']]
        recovery=failed['recovery_proposals'][0]
        assert recovery['status']=='PENDING_APPROVAL'
        assert recovery['actions'][0]['vehicle_id']!='scout-1'
        assert client.post(f"/api/missions/{recovery['id']}/approve").status_code==200
        for _ in range(500):
            state=client.post('/api/simulation/tick').json()
            statuses={m['id']:m['status'] for m in state['missions']}
            if statuses[recovery['id']]=='COMPLETED': break
        assert statuses[recovery['id']]=='COMPLETED'
        assert statuses[plan['id']]=='COMPLETED'
        # State must survive app process restart (same SQLite file).
        snap=db.load_snapshot()
        assert any(m['id']==plan['id'] for m in snap['missions'])


def test_px4_placeholder_never_sends_commands():
    from backend.adapters import PX4SITLAdapter
    import pytest
    with pytest.raises(RuntimeError,match='non-operational placeholder'):
        PX4SITLAdapter().dispatch(demo_fleet()['scout-1'],{'action':'goto','x':50,'y':50})

def test_coordinator_cannot_rewrite_planner_intent():
    import asyncio
    from backend.agents import AgentOrchestrator
    async def fake_planner(text, fleet):
        return [{'vehicle_id':'scout-1','action':'goto','x':50,'y':88}], 'offline'
    class BadCoordinator:
        async def coordinate(self, actions, fleet):
            return [{'vehicle_id':'relay-1','action':'goto','x':99,'y':99}], 'test', 'hallucinated reassignment'
    import backend.agents as agents
    old_planner=agents.planner
    try:
        agents.planner=fake_planner
        orchestrator=AgentOrchestrator(); orchestrator.coordinator=BadCoordinator()
        mission=asyncio.run(orchestrator.plan('Send Scout-1 north',demo_fleet(),[]))
        assert mission['status']=='PENDING_APPROVAL'
        assert mission['actions'][0]['vehicle_id']=='scout-1'
        assert 'original proposal preserved' in mission['agent_trace'][1]
    finally:
        agents.planner=old_planner

def test_api_serves_dashboard_and_enforces_approval_gate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'dashboard.sqlite3')
    with TestClient(main.app) as client:
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200
        client.post('/api/fleet/seed')
        plan=client.post('/api/plan',json={'instruction':'Send Scout-1 north.'}).json()
        before=client.get('/api/state').json()['fleet'][0]
        assert before['status']=='ready'
        assert client.post(f"/api/missions/{plan['id']}/reject").status_code==200
        after=client.get('/api/state').json()['fleet'][0]
        assert after['status']=='ready'


def test_wgs84_local_round_trip_and_geofence():
    from backend.geospatial import local_to_wgs84, wgs84_to_local, in_geofence, in_no_go_zone
    for point in [(10, 10), (50, 50), (88, 50)]:
        lat, lon = local_to_wgs84(*point)
        x, y = wgs84_to_local(lat, lon)
        assert abs(x - point[0]) < 1e-6
        assert abs(y - point[1]) < 1e-6
    assert in_geofence(50, 50)
    assert not in_geofence(1, 50)
    assert in_no_go_zone(30, 70)


def test_safety_policy_rejects_no_go_waypoint():
    from backend.agents import SafetyPolicyAgent
    fleet = {k: v.public() for k, v in demo_fleet().items()}
    actions, errors = SafetyPolicyAgent().validate(
        [{"vehicle_id": "scout-1", "action": "goto", "x": 30, "y": 70}], fleet
    )
    assert not actions
    assert any("restricted no-go zone" in e for e in errors)


def test_geospatial_map_tasking_end_to_end(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import backend.db as db
    from backend.main import app
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "omnifleet-test.sqlite3")
    with TestClient(app) as client:
        client.post("/api/fleet/seed").raise_for_status()
        config = client.get("/api/map/config").json()
        origin = config["origin"]
        assert config["width_m"] == 2000
        assert config["coordinate_system"].startswith("WGS84")
        proposal = client.post("/api/map/waypoint", json={
            "vehicle_id": "scout-1", "latitude": origin["lat"], "longitude": origin["lon"]
        })
        assert proposal.status_code == 200, proposal.text
        mission = proposal.json()
        assert mission["status"] == "PENDING_APPROVAL"
        assert mission["actions"][0]["vehicle_id"] == "scout-1"
        assert abs(mission["actions"][0]["x"] - 50) < 1e-4
        approved = client.post(f"/api/missions/{mission['id']}/approve")
        assert approved.status_code == 200
        state = client.get("/api/state").json()
        vehicle = next(v for v in state["fleet"] if v["id"] == "scout-1")
        assert vehicle["target_latitude"] is not None
        assert vehicle["latitude"] is not None
        old_x = vehicle["x"]
        client.post("/api/simulation/tick").raise_for_status()
        moved = client.get("/api/state").json()
        moved_vehicle = next(v for v in moved["fleet"] if v["id"] == "scout-1")
        assert moved_vehicle["x"] > old_x
        # A coordinate that maps into the restricted local polygon must be blocked.
        from backend.geospatial import local_to_wgs84
        lat, lon = local_to_wgs84(30, 70)
        blocked = client.post("/api/map/waypoint", json={"vehicle_id": "scout-2", "latitude": lat, "longitude": lon})
        assert blocked.status_code == 422
        lat, lon = local_to_wgs84(2, 50)
        outside = client.post("/api/map/waypoint", json={"vehicle_id": "scout-2", "latitude": lat, "longitude": lon})
        assert outside.status_code == 422
        # Revalidate immediately before dispatch: a vehicle that fails after proposal cannot be tasked.
        proposal2 = client.post("/api/map/waypoint", json={
            "vehicle_id": "scout-2", "latitude": origin["lat"], "longitude": origin["lon"]
        })
        assert proposal2.status_code == 200
        mission2 = proposal2.json()
        client.post("/api/vehicles/scout-2/fail").raise_for_status()
        refused = client.post(f"/api/missions/{mission2['id']}/approve")
        assert refused.status_code == 409
        refreshed = client.get("/api/state").json()
        failed_mission = next(m for m in refreshed["missions"] if m["id"] == mission2["id"])
        assert failed_mission["status"] == "REJECTED"


def test_coverage_planner_splits_disjoint_sectors_and_keeps_reserve():
    from backend.coverage import plan_coverage
    from backend.geospatial import local_to_wgs84
    fleet = demo_fleet()
    polygon = [local_to_wgs84(x, y) for x, y in [(48, 30), (88, 30), (88, 58), (48, 58)]]
    result = plan_coverage([{'latitude': p[0], 'longitude': p[1]} for p in polygon], fleet, 80)
    assert result['sector_count'] == 2
    assert result['reserve_vehicle'] == 'Relay-1'
    assert result['overlap_check'].startswith('PASS')
    assert all(len(a['route_points']) >= 2 for a in result['assignments'])
    assert result['assignments'][0]['sector_bounds_local']['east'] <= result['assignments'][1]['sector_bounds_local']['west']


def test_coverage_planner_rejects_no_go_and_outside_geofence():
    import pytest
    from backend.coverage import plan_coverage
    from backend.geospatial import local_to_wgs84
    fleet = demo_fleet()
    for points in [[(22, 65), (40, 65), (40, 78), (22, 78)], [(1, 30), (15, 30), (15, 45), (1, 45)]]:
        polygon = [local_to_wgs84(x, y) for x, y in points]
        with pytest.raises(ValueError):
            plan_coverage([{'latitude': p[0], 'longitude': p[1]} for p in polygon], fleet)


def test_coverage_mission_end_to_end_and_reserve_recovery(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    from backend.geospatial import local_to_wgs84
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'coverage-e2e.sqlite3')
    polygon = [local_to_wgs84(x, y) for x, y in [(48, 30), (58, 30), (58, 38), (48, 38)]]
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed').raise_for_status()
        proposal = client.post('/api/missions/coverage/plan', json={
            'polygon': [{'latitude': p[0], 'longitude': p[1]} for p in polygon],
            'lane_spacing_m': 150
        })
        assert proposal.status_code == 200, proposal.text
        mission = proposal.json()
        assert mission['status'] == 'PENDING_APPROVAL'
        assert len(mission['actions']) == 2
        assert mission['coverage_summary']['reserve_vehicle'] == 'Relay-1'
        assert client.post(f"/api/missions/{mission['id']}/approve").status_code == 200
        # Fail one assigned asset; the reserve is still ready and can take over the sector.
        failed_id = mission['actions'][0]['vehicle_id']
        failure = client.post(f'/api/vehicles/{failed_id}/fail').json()
        assert failure['degraded_missions'] == [mission['id']]
        recovery = failure['recovery_proposals'][0]
        assert recovery['status'] == 'PENDING_APPROVAL'
        assert recovery['actions'][0]['action'] == 'coverage'
        assert recovery['actions'][0]['vehicle_id'] == 'relay-1'
        assert client.post(f"/api/missions/{recovery['id']}/approve").status_code == 200
        for _ in range(500):
            state = client.post('/api/simulation/tick').json()
            statuses = {m['id']: m['status'] for m in state['missions']}
            if statuses[recovery['id']] == 'COMPLETED' and statuses[mission['id']] == 'COMPLETED':
                break
        assert statuses[recovery['id']] == 'COMPLETED'
        assert statuses[mission['id']] == 'COMPLETED'


def test_coverage_planner_rejects_concave_boundary_for_safe_sweep():
    import pytest
    from backend.coverage import plan_coverage
    from backend.geospatial import local_to_wgs84
    # Concave chevron inside the operating geofence.
    points = [(30, 30), (75, 30), (50, 45), (75, 65), (30, 65)]
    polygon = [local_to_wgs84(x, y) for x, y in points]
    with pytest.raises(ValueError, match='convex'):
        plan_coverage([{'latitude': p[0], 'longitude': p[1]} for p in polygon], demo_fleet())


def test_safety_rejects_coverage_segment_crossing_no_go_zone():
    from backend.agents import SafetyPolicyAgent
    fleet = {k: v.public() for k, v in demo_fleet().items()}
    actions, errors = SafetyPolicyAgent().validate([{
        'vehicle_id': 'scout-1', 'action': 'coverage', 'x': 10, 'y': 70,
        'route_points': [{'x': 10, 'y': 70}, {'x': 50, 'y': 70}]
    }], fleet)
    assert not errors
    assert len(actions[0]['route_points']) > 2
    from backend.geospatial import segment_is_safe
    points=[(18,25)]+[(p['x'],p['y']) for p in actions[0]['route_points']]
    assert all(segment_is_safe(a,b) for a,b in zip(points,points[1:]))


def test_sim_speed_uses_metres_per_second_not_local_grid_units():
    from backend.core import Vehicle, tick
    v = Vehicle('v1','V1','quadrotor',10,10,20,90,'moving',4,['navigation'],
                target_x=30,target_y=10,max_accel=100)
    fleet={'v1':v}
    tick(fleet,1.0)
    # 4 m/s for one second in a 2 km / 100-unit theatre is 0.2 local units.
    assert abs(v.x-10.2) < 1e-6
    assert abs(v.speed-4.0) < 1e-6


def test_seeded_fleet_starts_outside_restricted_zone():
    from backend.geospatial import in_no_go_zone
    fleet=demo_fleet()
    assert all(not in_no_go_zone(v.x,v.y) for v in fleet.values())


def test_vehicle_separation_guard_holds_vehicles_that_start_inside_clearance():
    from backend.core import Vehicle, tick
    first=Vehicle('a','A','quadrotor',19.8,20,20,90,'moving',4,['navigation'],target_x=20.2,target_y=20.2,max_accel=100)
    second=Vehicle('b','B','quadrotor',20,19.8,20,90,'moving',4,['navigation'],target_x=20.2,target_y=20.2,max_accel=100)
    fleet={'a':first,'b':second}
    tick(fleet,1.0)
    assert (first.x,first.y)==(19.8,20)
    assert (second.x,second.y)==(20,19.8)


def test_vehicle_separation_guard_prevents_head_on_swap_collision():
    from backend.core import Vehicle, tick
    first=Vehicle('a','A','quadrotor',49,50,20,90,'moving',20,['navigation'],target_x=53,target_y=50,max_accel=100)
    second=Vehicle('b','B','quadrotor',53,50,20,90,'moving',20,['navigation'],target_x=49,target_y=50,max_accel=100)
    fleet={'a':first,'b':second}
    tick(fleet,2.0)
    # The higher-priority vehicle may advance only to the clearance boundary;
    # the yielding vehicle remains stationary and the pair never overlaps.
    assert (first.x,first.y)==(51,50)
    assert (second.x,second.y)==(53,50)
    assert ((first.x-second.x)**2+(first.y-second.y)**2)**0.5 >= 2.0
    # The yielding asset receives a deterministic sidestep route; the pair
    # can separate and finish instead of remaining permanently deadlocked.
    for _ in range(10):
        tick(fleet,2.0)
        separation=((first.x-second.x)**2+(first.y-second.y)**2)**0.5
        assert separation >= 2.0-1e-6
    assert first.status=='ready' and second.status=='ready'


def test_route_planner_detours_around_simulated_structure_obstacle():
    from backend.geospatial import plan_safe_route, segment_is_safe, in_obstacle
    start=(55,70); target=(80,70)
    route=plan_safe_route(start,target)
    assert len(route)>1
    points=[start]+[(p['x'],p['y']) for p in route]
    assert all(segment_is_safe(a,b) for a,b in zip(points,points[1:]))
    assert not in_obstacle(*target)



def test_route_planner_detours_around_moving_obstacle_and_map_exposes_it():
    from backend.geospatial import reset_dynamic_obstacles, plan_safe_route, segment_is_safe, dynamic_obstacle_state
    reset_dynamic_obstacles()
    start=(43,48); target=(65,48)
    route=plan_safe_route(start,target)
    points=[start]+[(p['x'],p['y']) for p in route]
    assert len(route)>1
    assert all(segment_is_safe(a,b) for a,b in zip(points,points[1:]))
    obstacle=dynamic_obstacle_state()[0]
    assert obstacle['moving'] is True and obstacle['id']=='moving-obstacle-1'

def test_safety_rejects_waypoint_inside_simulated_obstacle():
    from backend.agents import SafetyPolicyAgent
    fleet={k:v.public() for k,v in demo_fleet().items()}
    actions,errors=SafetyPolicyAgent().validate([{'vehicle_id':'scout-1','action':'goto','x':67,'y':70}],fleet)
    assert not actions
    assert any('simulated obstacle' in e for e in errors)


def test_waypoint_route_automatically_detours_around_restricted_zone():
    from backend.agents import SafetyPolicyAgent
    from backend.geospatial import segment_is_safe
    fleet={k:v.public() for k,v in demo_fleet().items()}
    actions,errors=SafetyPolicyAgent().validate([{'vehicle_id':'scout-1','action':'goto','x':50,'y':88}],fleet)
    assert not errors
    route=actions[0]['route_points']
    assert len(route)>1
    points=[(fleet['scout-1']['x'],fleet['scout-1']['y'])]+[(p['x'],p['y']) for p in route]
    assert all(segment_is_safe(a,b) for a,b in zip(points,points[1:]))


def test_low_battery_emergency_landing_is_proposed_when_return_home_energy_is_insufficient(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'battery-emergency.sqlite3')
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed').raise_for_status()
        main.fleet['scout-1'].x=90.0; main.fleet['scout-1'].y=90.0; main.fleet['scout-1'].battery_pct=6.0
        client.post('/api/simulation/tick').raise_for_status()
        missions=client.get('/api/state').json()['missions']
        recovery=next(m for m in missions if m.get('provider')=='deterministic-battery-recovery')
        assert recovery['status']=='PENDING_APPROVAL'
        assert recovery['emergency_recovery'] is True
        assert recovery['actions'][0]['action']=='land'
        approved=client.post(f"/api/missions/{recovery['id']}/approve")
        assert approved.status_code==200, approved.text
        assert main.fleet['scout-1'].status=='landed'


def test_very_low_battery_also_generates_recovery_proposal(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'battery-critical.sqlite3')
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed').raise_for_status()
        main.fleet['scout-1'].battery_pct=4.9
        client.post('/api/simulation/tick').raise_for_status()
        missions=client.get('/api/state').json()['missions']
        recovery=next(m for m in missions if m.get('provider')=='deterministic-battery-recovery')
        assert recovery['status']=='PENDING_APPROVAL'
        assert recovery['actions'][0]['action'] in ('return_home','land')


def test_mission_monitor_does_not_mark_premature_landing_as_completed():
    from backend.agents import MissionMonitorAgent
    from backend.core import demo_fleet
    fleet=demo_fleet(); vehicle=fleet['scout-1']
    mission={'status':'EXECUTING','actions':[{'vehicle_id':'scout-1','action':'goto','x':40,'y':40}]}
    vehicle.status='landed'
    assert MissionMonitorAgent().evaluate(mission,fleet)=='DEGRADED'
    vehicle.status='ready'
    assert MissionMonitorAgent().evaluate(mission,fleet)=='COMPLETED'


def test_return_home_validation_rejects_insufficient_energy():
    from backend.agents import SafetyPolicyAgent
    from backend.core import demo_fleet
    fleet={k:v.public() for k,v in demo_fleet().items()}
    fleet['scout-1'].update({'x':90.0,'y':90.0,'battery_pct':6.0,'status':'low_battery'})
    actions,errors=SafetyPolicyAgent().validate([{'vehicle_id':'scout-1','action':'return_home'}],fleet)
    assert not actions
    assert any('cannot safely return home' in error for error in errors)


def test_vehicle_separation_guard_allows_monotonic_escape_from_existing_overlap():
    from backend.core import Vehicle, tick
    first=Vehicle('a','A','quadrotor',10,10,20,90,'moving',4,['navigation'],target_x=5,target_y=10,max_accel=100)
    second=Vehicle('b','B','quadrotor',11,10,20,90,'moving',4,['navigation'],target_x=16,target_y=10,max_accel=100)
    fleet={'a':first,'b':second}
    start=((first.x-second.x)**2+(first.y-second.y)**2)**0.5
    tick(fleet,1.0)
    end=((first.x-second.x)**2+(first.y-second.y)**2)**0.5
    assert end > start
    assert first.x < 10 and second.x > 11


def test_moving_obstacle_avoidance_completes_route_without_entering_obstacle():
    from backend.core import Vehicle, dispatch, tick
    from backend.geospatial import reset_dynamic_obstacles, advance_dynamic_obstacles, dynamic_obstacle_polygons, in_obstacle, plan_safe_route
    reset_dynamic_obstacles()
    vehicle=Vehicle('moving-test','Moving Test','quadrotor',50,48,20,90,'ready',4,['navigation'],max_accel=100)
    route=plan_safe_route((vehicle.x,vehicle.y),(58,48))
    dispatch(vehicle,{'action':'goto','x':58,'y':48,'route_points':route})
    fleet={vehicle.id:vehicle}
    for _ in range(120):
        advance_dynamic_obstacles(1.0,[(vehicle.x,vehicle.y)])
        tick(fleet,dynamic_obstacle_polygons=dynamic_obstacle_polygons())
        assert not in_obstacle(vehicle.x,vehicle.y)
        if vehicle.status=='ready':
            break
    assert vehicle.status=='ready'
    assert (vehicle.x,vehicle.y)==(58,48)


def test_very_low_battery_ground_vehicle_gets_operator_approved_safe_stop(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'ground-battery-emergency.sqlite3')
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed').raise_for_status()
        main.fleet['relay-1'].x=95.0; main.fleet['relay-1'].y=90.0
        main.fleet['relay-1'].battery_pct=4.9; main.fleet['relay-1'].status='low_battery'
        client.post('/api/simulation/tick').raise_for_status()
        recovery=next(m for m in client.get('/api/state').json()['missions']
                      if m.get('provider')=='deterministic-battery-recovery')
        assert recovery['status']=='PENDING_APPROVAL'
        assert recovery['actions'][0]['action']=='hold'
        approved=client.post(f"/api/missions/{recovery['id']}/approve")
        assert approved.status_code==200,approved.text
        assert main.fleet['relay-1'].status=='holding'


def test_emergency_recovery_is_not_proposed_inside_restricted_zone(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import db, main
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'unsafe-battery-emergency.sqlite3')
    with TestClient(main.app) as client:
        client.post('/api/fleet/seed').raise_for_status()
        main.fleet['scout-1'].x=30.0; main.fleet['scout-1'].y=70.0
        main.fleet['scout-1'].battery_pct=4.9; main.fleet['scout-1'].status='low_battery'
        client.post('/api/simulation/tick').raise_for_status()
        recovery=next(m for m in client.get('/api/state').json()['missions']
                      if m.get('provider')=='deterministic-battery-recovery')
        assert recovery['status']=='RECOVERY_UNAVAILABLE'
        assert recovery['actions']==[]


def test_energy_estimator_accounts_for_acceleration():
    from backend.agents import _required_battery_pct
    slow={'x':10,'y':10,'max_speed_mps':4,'max_accel':0.1}
    fast={'x':10,'y':10,'max_speed_mps':4,'max_accel':10.0}
    route=[{'x':15,'y':10}]
    assert _required_battery_pct(slow,route) > _required_battery_pct(fast,route)


def test_mission_safety_rejects_targets_inside_minimum_vehicle_separation():
    from backend.agents import SafetyPolicyAgent
    fleet={k:v.public() for k,v in demo_fleet().items()}
    actions,errors=SafetyPolicyAgent().validate([
        {'vehicle_id':'scout-1','action':'goto','x':50,'y':50},
        {'vehicle_id':'scout-2','action':'goto','x':51,'y':50},
    ],fleet)
    assert not actions
    assert any('minimum vehicle separation' in e for e in errors)


def test_permanently_blocked_mission_becomes_safe_hold_not_infinite_execution():
    from backend.core import Vehicle, tick
    first=Vehicle('a','A','quadrotor',50,50,20,90,'moving',4,['navigation'],target_x=51,target_y=50,max_accel=100)
    second=Vehicle('b','B','quadrotor',51,50,20,90,'ready',4,['navigation'],max_accel=100)
    fleet={'a':first,'b':second}
    for _ in range(10):
        tick(fleet,1.0)
    assert first.status=='holding'
    assert first.target_x is None and first.target_y is None


def test_perpendicular_crossing_routes_detour_without_breaching_separation():
    from backend.core import Vehicle, tick
    first=Vehicle('a','A','quadrotor',48,50,20,90,'moving',20,['navigation'],target_x=52,target_y=50,max_accel=100)
    second=Vehicle('b','B','quadrotor',50,48,20,90,'moving',20,['navigation'],target_x=50,target_y=52,max_accel=100)
    fleet={'a':first,'b':second}
    minimum=100.0
    for _ in range(20):
        tick(fleet,2.0)
        separation=((first.x-second.x)**2+(first.y-second.y)**2)**0.5
        minimum=min(minimum,separation)
        assert separation >= 2.0-1e-6
        if first.status=='ready' and second.status=='ready':
            break
    assert first.status=='ready' and second.status=='ready'
    assert minimum >= 2.0-1e-6
