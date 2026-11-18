import os
from pathlib import Path
from datetime import datetime,timezone
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()  # Load theatre/database settings before importing modules that read them.
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .core import demo_fleet,dispatch,tick,vehicle_from_dict
from .schemas import (PlanRequest, MapWaypointRequest, CoveragePlanRequest, SwarmConfigRequest,
                      VehicleRadioRequest, SwarmBroadcastRequest, DetectionEventRequest, PeerTestRequest,
                      TestObjectCreateRequest, TestObjectUpdateRequest, SensorVehicleConfigRequest, SensorAutomationRequest)
from .geospatial import (map_config, wgs84_to_local, local_to_wgs84, in_geofence, in_no_go_zone, in_obstacle,
                         advance_dynamic_obstacles, dynamic_obstacle_polygons, dynamic_obstacle_state, reset_dynamic_obstacles)
from .agents import AgentOrchestrator
from .db import load_snapshot,save_snapshot
from .adapters import SimulatedVehicleAdapter
from .coverage import plan_coverage
from .swarm import SwarmNetwork
from .sensors import SensorSimulation
sensor_system = SensorSimulation()

@asynccontextmanager
async def lifespan(app):
    snap=load_snapshot()
    if snap:
        fleet.update({k:vehicle_from_dict(v) for k,v in snap.get("fleet",{}).items()})
        orchestrator.missions=snap.get("missions",[]); events.extend(snap.get("events",[])); swarm.restore(snap.get("swarm"), fleet)
        sensor_system.restore(snap.get("sensors"), fleet)
    else:
        fleet.update(demo_fleet()); log("Simulation","Demo fleet initialized")
    sensor_system.ensure_fleet(fleet)
    swarm.update_link_geometry(fleet, sensor_system.settings)
    if not sensor_system.telemetry:
        sensor_system.capture_telemetry(fleet, swarm)
    persist()
    yield

app=FastAPI(title="OmniFleet AI",version="0.9.2",lifespan=lifespan)
BASE=Path(__file__).resolve().parent.parent
app.mount("/static",StaticFiles(directory=BASE/"frontend"),name="static")
fleet={}; events=[]; orchestrator=AgentOrchestrator(); adapter=SimulatedVehicleAdapter(); swarm=SwarmNetwork()
def log(agent,msg):
    events.append({"time":datetime.now(timezone.utc).isoformat(),"agent":agent,"message":msg}); del events[:-200]
    sensor_system.record_event(str(agent).upper().replace(" ", "_"), None, {"message": str(msg)})
    persist()
def persist(): save_snapshot(fleet,orchestrator.missions,events,swarm.snapshot(),sensor_system.snapshot())
def state():
    swarm.ensure_fleet(fleet)
    moving=sum(v.status in ("moving","returning") for v in fleet.values()); low=[v.name for v in fleet.values() if v.battery_pct<20]
    return {"fleet":[{**v.public(),"latitude":local_to_wgs84(v.x,v.y)[0],"longitude":local_to_wgs84(v.x,v.y)[1],"target_latitude":local_to_wgs84(v.target_x,v.target_y)[0] if v.target_x is not None else None,"target_longitude":local_to_wgs84(v.target_x,v.target_y)[1] if v.target_y is not None else None} for v in fleet.values()],"missions":orchestrator.missions,"events":list(reversed(events[-60:])),
      "summary":{"vehicles_total":len(fleet),"vehicles_moving":moving,"low_battery":low,"missions_total":len(orchestrator.missions)},"provider":os.getenv("AI_PROVIDER","offline"),"swarm_connectivity":swarm.public_state(fleet)["connectivity"],
      "environment":{"moving_obstacles":dynamic_obstacle_state()}}
@app.get("/")
def home(): return FileResponse(BASE/"frontend"/"index.html")
@app.get("/api/health")
def health(): return {"ok":True,"name":"OmniFleet AI","version":"0.9.2","adapter":adapter.name,"swarm":"simulated-structured-message-bus"}
@app.get("/api/state")
def get_state(): return state()
@app.get("/api/events")
def get_events(): return list(reversed(events[-60:]))
@app.get("/api/map/config")
def get_map_config(): return map_config()
@app.post("/api/map/waypoint")
def create_map_waypoint(req: MapWaypointRequest):
    v=fleet.get(req.vehicle_id)
    if not v: raise HTTPException(404,"Vehicle not found")
    if v.failed or v.status not in ("ready","holding"): raise HTTPException(409,"Vehicle is not available for a new task")
    if "navigation" not in v.capabilities: raise HTTPException(409,"Vehicle does not support waypoint navigation")
    x,y=wgs84_to_local(req.latitude,req.longitude)
    if not (0 <= x <= 100 and 0 <= y <= 100 and in_geofence(x,y)):
        raise HTTPException(422,"Selected waypoint is outside the operating geofence")
    if in_no_go_zone(x,y): raise HTTPException(422,"Selected waypoint is inside a restricted no-go zone")
    action={"vehicle_id":v.id,"vehicle_name":v.name,"action":"goto","x":round(x,4),"y":round(y,4),"note":"Map-selected WGS84 waypoint"}
    checked, errors = orchestrator.safety.validate([action], {item.id:item.public() for item in fleet.values()})
    if errors:
        raise HTTPException(422, "; ".join(errors))
    action=checked[0]
    mission={"id":str(__import__('uuid').uuid4())[:8],"instruction":f"Map waypoint for {v.name} at {req.latitude:.6f}, {req.longitude:.6f}",
      "status":"PENDING_APPROVAL","actions":[action],"checks":["Vehicle identity verified","Vehicle availability verified","WGS84 converted to local theatre coordinates","Operating geofence passed","No-go zone check passed","Human approval required"],
      "agent_trace":["Map Tasking: operator selected a geographic waypoint","Coordinate Adapter: converted WGS84 to local simulation coordinates","Safety & Policy: geofence and restricted-zone checks passed"],
      "provider":"map-tasking","coordinator_provider":"deterministic-map-tasking","created_at":datetime.now(timezone.utc).isoformat(),
      "map_target":{"latitude":req.latitude,"longitude":req.longitude}}
    orchestrator.missions.insert(0,mission); log("Map Tasking",f"Waypoint proposal created for {v.name}"); persist(); return mission
@app.post("/api/missions/coverage/plan")
def plan_coverage_mission(req: CoveragePlanRequest):
    try:
        result = plan_coverage([p.model_dump() for p in req.polygon], fleet, req.lane_spacing_m)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    mission={"id":str(__import__('uuid').uuid4())[:8],
      "instruction":f"Coordinated area coverage across {result['sector_count']} fleet sector(s)",
      "status":"PENDING_APPROVAL","actions":result["assignments"],
      "checks":["Operator-drawn boundary converted from WGS84","Operating geofence validation passed",
        "Restricted-zone intersection check passed","Sector bands generated without overlap",
        "Sweep waypoints validated","Vehicle availability and navigation capability checked",
        "Human approval required"],
      "coverage_summary":{k:v for k,v in result.items() if k!="assignments"},
      "coverage_polygon": [p.model_dump() for p in req.polygon],
      "agent_trace":["Coverage Planner: generated deterministic lawnmower sweep lanes",
        "Fleet Coordinator: allocated disjoint sectors to available navigation-capable assets",
        "Safety & Policy: geofence, restricted-zone and waypoint checks passed"],
      "provider":"deterministic-coverage-planner","coordinator_provider":"deterministic-sector-allocation",
      "created_at":datetime.now(timezone.utc).isoformat()}
    orchestrator.missions.insert(0,mission); log("Coverage Planner",f"Coverage proposal {mission['id']} created with {result['waypoint_count']} waypoints")
    persist(); return mission

@app.get("/api/sensors/state")
def get_sensor_state():
    return sensor_system.state(fleet)

@app.post("/api/sensors/objects")
def create_test_object(req: TestObjectCreateRequest):
    try:
        item = sensor_system.create_object(req.x, req.y, req.label, req.category, req.difficulty, req.visible)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    log("Human Operator", f"Placed virtual test object {item['label']} at ({item['x']}, {item['y']})")
    return item

@app.put("/api/sensors/objects/{object_id}")
def update_test_object(object_id: str, req: TestObjectUpdateRequest):
    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    try:
        item = sensor_system.update_object(object_id, patch)
    except KeyError:
        raise HTTPException(404, "Test object not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    log("Human Operator", f"Updated virtual test object {object_id}")
    return item

@app.delete("/api/sensors/objects/{object_id}")
def delete_test_object(object_id: str):
    try:
        result = sensor_system.delete_object(object_id)
    except KeyError:
        raise HTTPException(404, "Test object not found")
    log("Human Operator", f"Removed virtual test object {object_id}")
    return result

@app.put("/api/sensors/vehicles/{vehicle_id}")
def configure_sensor_vehicle(vehicle_id: str, req: SensorVehicleConfigRequest):
    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    try:
        result = sensor_system.configure_vehicle(vehicle_id, patch, fleet)
    except KeyError:
        raise HTTPException(404, "Vehicle not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    swarm.update_link_geometry(fleet, sensor_system.settings)
    log("Human Operator", f"Updated simulated sensor configuration for {vehicle_id}")
    return result

def process_sensor_automation(observations=None):
    """Aggregate persisted observations and retry coordination until a proposal exists."""
    policy = sensor_system.automation
    if not policy.get("enabled"):
        return []
    grouped = {}
    # Use the full observation history: corroboration may arrive on different ticks.
    for obs in sensor_system.observations:
        grouped.setdefault((obs["object_id"], obs["object_revision"]), []).append(obs)
    results = []
    for (object_id, revision), rows in grouped.items():
        key = f"{object_id}:{revision}"
        if key in sensor_system._automated_keys:
            continue
        if sensor_system.tick_count < sensor_system._automation_retry_after.get(key, 0):
            continue
        qualifying = [r for r in rows if r.get("confidence", 0) >= policy["min_confidence"]]
        sources = {r["source_vehicle_id"] for r in qualifying}
        if qualifying and in_obstacle(float(qualifying[0]["x"]), float(qualifying[0]["y"])):
            sensor_system._automated_keys.add(key)
            sensor_system.record_event("SENSOR_AUTOMATION_BLOCKED", None,
                {"object_id":object_id,"reason":"Target is inside a simulated static obstacle; no safe inspection route exists"})
            continue
        if len(sources) < policy["min_sources"]:
            continue
        # An offline observer cannot originate a live coordination request. Prefer an
        # online corroborating observer and leave the object retryable if none exists.
        online = [r for r in qualifying if swarm.radios.get(r["source_vehicle_id"], False)
                  and sensor_system.settings.get(r["source_vehicle_id"], {}).get("sensor_enabled", True)]
        if not online:
            sensor_system._automation_retry_after[key] = sensor_system.tick_count + 3
            continue
        source_obs = max(online, key=lambda r: r["confidence"])
        try:
            request = DetectionEventRequest(source_vehicle_id=source_obs["source_vehicle_id"],
                x=source_obs["x"], y=source_obs["y"], label=source_obs["label"], confidence=source_obs["confidence"])
            result = swarm_detection(request)
        except HTTPException as exc:
            sensor_system._automation_retry_after[key] = sensor_system.tick_count + 3
            sensor_system.record_event("SENSOR_AUTOMATION_RETRY", source_obs["source_vehicle_id"],
                {"object_id":object_id,"reason":exc.detail,"retry_after_tick":sensor_system._automation_retry_after[key]})
            continue
        proposal = result.get("proposal")
        if result.get("coordination_pending"):
            coordination_id=result.get("coordination_id")
            context=swarm.pending_coordination.get(coordination_id)
            if context is not None:
                context["automation_key"]=key
            delay=int(swarm.config.get("network_latency_ticks",0))
            sensor_system._automation_retry_after[key] = sensor_system.tick_count + max(4, delay*2+3)
            sensor_system.record_event("SENSOR_AUTOMATION_PENDING", source_obs["source_vehicle_id"],
                {"object_id":object_id,"coordination_id":coordination_id,
                 "reason":"Coordination messages are in transit; awaiting task offers"})
            continue
        if not proposal or proposal.get("status") != "PENDING_APPROVAL":
            sensor_system._automation_retry_after[key] = sensor_system.tick_count + 3
            sensor_system.record_event("SENSOR_AUTOMATION_RETRY", source_obs["source_vehicle_id"],
                {"object_id":object_id,"reason":"No valid inspection offer/proposal; retry scheduled",
                 "retry_after_tick":sensor_system._automation_retry_after[key]})
            continue
        sensor_system._automated_keys.add(key)
        sensor_system._automation_retry_after.pop(key, None)
        results.append({"object_id": object_id, "object_revision": revision,
                        "qualifying_sources": sorted(sources), **result})
        sensor_system.record_event("SENSOR_AUTOMATION_PROPOSAL", source_obs["source_vehicle_id"],
            {"object_id": object_id, "sources": sorted(sources), "proposal_id": proposal["id"]})
    return results

@app.get("/api/sensors/automation")
def get_sensor_automation():
    return dict(sensor_system.automation)

@app.put("/api/sensors/automation")
def update_sensor_automation(req: SensorAutomationRequest):
    patch = req.model_dump(exclude_unset=True)
    sensor_system.automation.update(patch)
    persist()
    return dict(sensor_system.automation)

@app.post("/api/sensors/scan")
def scan_test_objects():
    created = sensor_system.scan(fleet, swarm)
    proposals = process_sensor_automation(created)
    log("Sensor Simulation", f"Manual scan completed; {len(created)} new vehicle observation(s), {len(proposals)} automated inspection proposal(s)")
    return {"new_observations": created, "count": len(created), "automated_proposals": proposals,
            "automation": dict(sensor_system.automation), "sensor_state": sensor_system.state(fleet)}

@app.get("/api/blackbox")
def get_blackbox(vehicle_id: str | None = Query(default=None, max_length=80),
                 limit: int = Query(default=180, ge=1, le=500)):
    if vehicle_id is not None and vehicle_id not in fleet:
        raise HTTPException(404, "Vehicle not found")
    return sensor_system.blackbox(vehicle_id, limit)

@app.get("/api/blackbox/events")
def get_blackbox_events(vehicle_id: str | None = Query(default=None, max_length=80),
                        limit: int = Query(default=100, ge=1, le=300)):
    if vehicle_id is not None and vehicle_id not in fleet:
        raise HTTPException(404, "Vehicle not found")
    return {"events": sensor_system.blackbox(vehicle_id, limit)["events"][:limit]}

@app.get("/api/swarm/state")
def get_swarm_state():
    return swarm.public_state(fleet)

@app.put("/api/swarm/config")
def update_swarm_config(req: SwarmConfigRequest):
    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    try:
        result = swarm.configure(patch, fleet)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    log("Human Operator", "Updated swarm network configuration: " + ", ".join(f"{k}={v}" for k,v in patch.items()))
    return result

@app.put("/api/swarm/vehicles/{vid}/radio")
def update_vehicle_radio(vid: str, req: VehicleRadioRequest):
    try:
        result = swarm.set_radio(vid, req.enabled, fleet)
    except KeyError:
        raise HTTPException(404, "Vehicle not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    log("Human Operator", f"{vid} communication radio {'enabled' if req.enabled else 'disabled'}")
    persist()
    return result

@app.post("/api/swarm/broadcast")
def swarm_broadcast(req: SwarmBroadcastRequest):
    recipients = req.recipients
    if recipients is not None and any(v not in fleet for v in recipients):
        raise HTTPException(404, "One or more broadcast recipients are unknown")
    message = swarm.publish("operator", "OPERATOR_ANNOUNCEMENT", {"text": req.message, "executable": False}, recipients)
    log("Human Operator", f"Operator broadcast {message['status'].lower()} to {len(message['delivered_to'])} vehicle(s)")
    persist()
    return message

@app.post("/api/swarm/status-request")
def swarm_status_request():
    request_message = swarm.publish("operator", "STATUS_REQUEST", {"requested_fields": ["status", "battery_pct", "position"]})
    reports = []
    for vid in request_message["delivered_to"]:
        v = fleet[vid]
        report = swarm.publish(vid, "STATUS_REPORT", {
            "vehicle_id": vid, "status": v.status, "battery_pct": round(v.battery_pct, 1),
            "position": {"x": round(v.x, 2), "y": round(v.y, 2)},
        }, ["operator"])
        if "operator" in report["delivered_to"]:
            reports.append(report)
    log("Swarm Network", f"Status poll received {len(reports)} vehicle report(s)")
    persist()
    return {"request": request_message, "reports": reports}

@app.post("/api/swarm/peer-test")
def swarm_peer_test(req: PeerTestRequest):
    if req.sender_vehicle_id not in fleet or req.recipient_vehicle_id not in fleet:
        raise HTTPException(404, "Peer-test vehicle not found")
    if req.sender_vehicle_id == req.recipient_vehicle_id:
        raise HTTPException(422, "Select two different vehicles")
    message = swarm.publish(req.sender_vehicle_id, "PEER_TEST", {"text": req.message, "test": True}, [req.recipient_vehicle_id])
    swarm.acknowledge(message)
    log("Swarm Network", f"Peer link test {message['status'].lower()}: {req.sender_vehicle_id} → {req.recipient_vehicle_id}")
    persist()
    return message

@app.post("/api/swarm/detections")
def swarm_detection(req: DetectionEventRequest):
    sensor_system.ensure_fleet(fleet)
    swarm.update_link_geometry(fleet, sensor_system.settings)
    source = fleet.get(req.source_vehicle_id)
    if not source:
        raise HTTPException(404, "Source vehicle not found")
    if source.failed or source.status in ("failed", "low_battery", "landed"):
        raise HTTPException(409, "Source vehicle cannot report a detection")
    if not swarm.radios.get(source.id, True) or not swarm.config["enabled"]:
        raise HTTPException(409, "Source vehicle has no active communications link")
    if not in_geofence(req.x, req.y) or in_no_go_zone(req.x, req.y):
        raise HTTPException(422, "Detection coordinate is outside the allowed demo operating area")
    detection, event_message = swarm.record_detection(source.id, req.x, req.y, req.label, req.confidence)
    eligible = [v for v in fleet.values() if v.id != source.id and not v.failed
                and v.status in ("ready", "holding") and v.battery_pct >= 20
                and "inspect" in (v.mission_types or []) and swarm.radios.get(v.id, True)]
    peer_negotiated = (swarm.config["coordination_mode"] == "hybrid"
                       and swarm.config["peer_mesh_enabled"]
                       and not swarm.config["coordinator_link_enabled"])
    request_sender = source.id if peer_negotiated else "coordinator"
    offer_recipient = source.id if peer_negotiated else "coordinator"
    task_request = swarm.publish(request_sender, "TASK_REQUEST", {
        "detection_id": detection["detection_id"], "objective": "inspect_detection",
        "target": {"x": req.x, "y": req.y}, "required_mission_type": "inspect",
        "source_vehicle_id": source.id,
        "coordination": "peer-negotiated" if peer_negotiated else "coordinator-managed",
    }, [v.id for v in eligible])
    if int(swarm.config.get("network_latency_ticks",0)) > 0:
        coordination_id=str(__import__('uuid').uuid4())[:10]
        swarm.pending_coordination[coordination_id]={
            "coordination_id":coordination_id,"detection":detection,
            "source_vehicle_id":source.id,"candidate_ids":[v.id for v in eligible],
            "offer_recipient":offer_recipient,"peer_negotiated":peer_negotiated,
            "task_request_id":task_request["id"],"offer_message_ids":{},
            "attempts":1,"next_retry_tick":swarm.tick_count+max(2,int(swarm.config["network_latency_ticks"])+1),
            "automation_key":None,
        }
        persist()
        return {"detection":detection,"detection_message":event_message,"task_request":task_request,
                "task_offers":[],"proposal":None,"coordination_pending":True,
                "coordination_id":coordination_id}
    offers = []
    if task_request["status"] in ("DELIVERED", "PARTIAL"):
        for candidate in eligible:
            if candidate.id not in task_request["delivered_to"]:
                continue
            offer = swarm.publish(candidate.id, "TASK_OFFER", {
                "detection_id": detection["detection_id"], "vehicle_id": candidate.id,
                "mission_type": "inspect", "distance_local": round(((candidate.x-req.x)**2+(candidate.y-req.y)**2)**0.5, 2),
                "battery_pct": round(candidate.battery_pct, 1),
                "coordination": "peer-negotiated" if peer_negotiated else "coordinator-managed",
            }, [offer_recipient])
            if offer_recipient in offer["delivered_to"]:
                offers.append((candidate, offer))
    proposal = None
    if offers:
        candidate, offer = min(offers, key=lambda item: ((item[0].x-req.x)**2+(item[0].y-req.y)**2)**0.5)
        action = {"vehicle_id": candidate.id, "vehicle_name": candidate.name, "action": "goto",
                  "x": round(req.x, 4), "y": round(req.y, 4), "note": "Peer-coordinated anomaly inspection; pending operator approval"}
        proposal = {"id":str(__import__('uuid').uuid4())[:8],
            "instruction":f"Investigate {req.label} reported by {source.name}",
            "status":"PENDING_APPROVAL", "actions":[action],
            "checks":["Detection event received through swarm message bus", "Inspection capability and vehicle availability verified",
                      "Candidate offers received", "Nearest eligible vehicle selected", "Geofence and restricted-zone validation passed", "Human approval required"],
            "agent_trace":[f"{source.name}: broadcast DETECTION_EVENT to the fleet", "Peer vehicles: received event and shared situational awareness",
                           f"{candidate.name}: returned TASK_OFFER", "Fleet Coordinator: selected nearest eligible inspection asset",
                           "Safety & Policy: proposal validated; operator approval required"],
            "provider":"swarm-detection-coordination", "coordinator_provider":"deterministic-peer-offers",
            "created_at":datetime.now(timezone.utc).isoformat(), "detection":detection,
            "coordination_mode":"peer-negotiated" if peer_negotiated else "coordinator-managed",
            "approval_requires_coordinator_link": True}
        checked, errors = orchestrator.safety.validate(proposal["actions"], {v.id:v.public() for v in fleet.values()})
        if errors:
            proposal["status"]="REJECTED"; proposal["checks"].extend(errors)
        else:
            proposal["actions"]=checked
        orchestrator.missions.insert(0, proposal)
        log("Swarm Coordinator", f"Inspection proposal {proposal['id']} created from detection {detection['detection_id']}")
    else:
        log("Swarm Coordinator", "Detection shared, but no eligible inspection vehicle could submit an offer")
    persist()
    return {"detection":detection, "detection_message":event_message, "task_request":task_request,
            "task_offers":[m for _,m in offers], "proposal":proposal}

def process_pending_coordination():
    """Complete latency-delayed TASK_REQUEST/TASK_OFFER exchanges by tick."""
    for coordination_id, context in list(swarm.pending_coordination.items()):
        request_message=next((m for m in swarm.messages if m.get("id")==context.get("task_request_id")),None)
        if request_message is None:
            swarm.pending_coordination.pop(coordination_id,None)
            continue
        offer_ids=context.setdefault("offer_message_ids",{})
        # A delivered request is acted upon by each compatible recipient.
        for candidate_id in request_message.get("delivered_to",[]):
            if candidate_id in offer_ids:
                continue
            candidate=fleet.get(candidate_id)
            if (candidate is None or candidate.failed or candidate.status not in ("ready","holding")
                    or candidate.battery_pct < 20 or "inspect" not in (candidate.mission_types or [])):
                continue
            target=context["detection"]
            offer=swarm.publish(candidate_id,"TASK_OFFER",{
                "detection_id":target["detection_id"],"vehicle_id":candidate_id,
                "mission_type":"inspect",
                "distance_local":round(((candidate.x-target["x"])**2+(candidate.y-target["y"])**2)**0.5,2),
                "battery_pct":round(candidate.battery_pct,1),
                "coordination":"peer-negotiated" if context["peer_negotiated"] else "coordinator-managed",
            },[context["offer_recipient"]])
            offer_ids[candidate_id]=offer["id"]

        delivered_offers=[]; offers_settled=True
        for candidate_id,message_id in list(offer_ids.items()):
            message=next((m for m in swarm.messages if m.get("id")==message_id),None)
            if message is None:
                continue
            if message.get("queued_to"):
                offers_settled=False
            if context["offer_recipient"] in message.get("delivered_to",[]):
                delivered_offers.append((fleet[candidate_id],message))
        request_settled=not request_message.get("queued_to")
        if not request_settled or not offers_settled:
            continue

        if delivered_offers:
            source=fleet.get(context["source_vehicle_id"])
            if source is not None:
                detection=context["detection"]
                ordered=sorted(delivered_offers,key=lambda item:item[1]["payload"].get("distance_local",float("inf")))
                selected=None; selected_actions=[]; rejection_errors=[]
                for candidate,offer in ordered:
                    action={"vehicle_id":candidate.id,"vehicle_name":candidate.name,"action":"goto",
                            "x":round(float(detection["x"]),4),"y":round(float(detection["y"]),4),
                            "note":"Latency-delayed peer inspection offer; pending operator approval"}
                    checked,errors=orchestrator.safety.validate([action],{v.id:v.public() for v in fleet.values()})
                    if not errors:
                        selected=(candidate,offer); selected_actions=checked; break
                    rejection_errors.extend(errors)
                if selected:
                    candidate,offer=selected
                    proposal={"id":str(__import__('uuid').uuid4())[:8],
                        "instruction":f"Investigate {detection['label']} reported by {source.name}",
                        "status":"PENDING_APPROVAL","actions":selected_actions,
                        "checks":["Delayed TASK_REQUEST delivered","Candidate TASK_OFFER delivered","Candidate compatibility and battery checked",
                                  "Safe route and restricted-zone validation passed","Human approval required"],
                        "agent_trace":[f"{source.name}: sent detection event","Swarm Network: delayed task request delivered",
                                      f"{candidate.name}: returned delayed TASK_OFFER","Fleet Coordinator: selected nearest safe eligible inspector",
                                      "Safety & Policy: operator approval remains mandatory"],
                        "provider":"swarm-detection-coordination","coordinator_provider":"deterministic-delayed-peer-offers",
                        "created_at":datetime.now(timezone.utc).isoformat(),"detection":detection,
                        "coordination_mode":"peer-negotiated" if context["peer_negotiated"] else "coordinator-managed",
                        "approval_requires_coordinator_link":True}
                    orchestrator.missions.insert(0,proposal)
                    log("Swarm Coordinator",f"Delayed inspection proposal {proposal['id']} created from detection {detection['detection_id']}")
                    automation_key=context.get("automation_key")
                    if automation_key:
                        sensor_system._automated_keys.add(automation_key)
                        sensor_system._automation_retry_after.pop(automation_key,None)
                else:
                    log("Swarm Coordinator","Delayed offers received, but no candidate passed route/energy validation: "+"; ".join(rejection_errors[:3]))
                    automation_key=context.get("automation_key")
                    if automation_key:
                        sensor_system._automation_retry_after[automation_key]=sensor_system.tick_count+3
            swarm.pending_coordination.pop(coordination_id,None)
            continue

        # No peer replied (link outage or deterministic packet loss). Retry a
        # bounded number of times; never let one dead exchange block the bus.
        if swarm.tick_count >= context.get("next_retry_tick",0):
            if int(context.get("attempts",1)) < 3:
                request=swarm.publish(context["source_vehicle_id"] if context["peer_negotiated"] else "coordinator",
                    "TASK_REQUEST",{
                        "detection_id":context["detection"]["detection_id"],"objective":"inspect_detection",
                        "target":{"x":context["detection"]["x"],"y":context["detection"]["y"]},
                        "required_mission_type":"inspect","source_vehicle_id":context["source_vehicle_id"],
                        "coordination":"peer-negotiated" if context["peer_negotiated"] else "coordinator-managed",
                    },context["candidate_ids"])
                context["task_request_id"]=request["id"]
                context["offer_message_ids"]={}
                context["attempts"]=int(context.get("attempts",1))+1
                context["next_retry_tick"]=swarm.tick_count+max(2,int(swarm.config.get("network_latency_ticks",0))+1)
            else:
                automation_key=context.get("automation_key")
                if automation_key:
                    sensor_system._automation_retry_after[automation_key]=sensor_system.tick_count+3
                log("Swarm Coordinator",f"Coordination {coordination_id} expired after bounded retries")
                swarm.pending_coordination.pop(coordination_id,None)


def _predicted_position(vehicle, seconds):
    """Predict position across the current route queue using simulator kinematics.

    Prediction uses small deterministic substeps, carries acceleration and
    speed limits through each active leg, and resets speed when a waypoint is
    reached, matching the simplified movement model used by ``core.tick``.
    """
    if seconds <= 0 or vehicle.status not in ("moving", "returning"):
        return (float(vehicle.x), float(vehicle.y))
    x,y=float(vehicle.x),float(vehicle.y)
    speed=max(0.0,float(vehicle.speed)); max_speed=max(0.0,float(vehicle.max_speed_mps))
    accel=max(0.0,float(vehicle.max_accel)); remaining=max(0.0,float(seconds))
    waypoints=[]
    if vehicle.target_x is not None and vehicle.target_y is not None:
        waypoints.append((float(vehicle.target_x),float(vehicle.target_y)))
    waypoints.extend((float(p["x"]),float(p["y"])) for p in (vehicle.route_queue or []))
    metres_per_unit=2000.0/100.0
    while remaining > 1e-9 and waypoints:
        tx,ty=waypoints[0]; dx,dy=tx-x,ty-y
        distance_local=(dx*dx+dy*dy)**0.5
        if distance_local <= 1e-9:
            x,y=tx,ty; waypoints.pop(0); speed=0.0; continue
        distance_m=distance_local*metres_per_unit
        desired=min(max_speed,(max(0.0,2.0*accel*distance_m))**0.5)
        step_dt=min(0.25,remaining)
        next_speed=max(0.0,speed+max(-accel*step_dt,min(accel*step_dt,desired-speed)))
        step_m=min(distance_m,next_speed*step_dt)
        step_local=step_m/metres_per_unit
        if step_m >= distance_m-1e-9:
            x,y=tx,ty; waypoints.pop(0); speed=0.0
        else:
            x += dx/distance_local*step_local
            y += dy/distance_local*step_local
            speed=next_speed
        remaining -= step_dt
    return (x,y)

def _time_synchronized_conflict(first, second, horizon_s=45.0, step_s=0.25, clearance_local=2.0):
    """Return a conflict only when vehicles approach within clearance at the same time."""
    best=float("inf"); best_t=0.0; best_points=None
    steps=max(1,int(horizon_s/step_s))
    for idx in range(steps+1):
        t=idx*step_s
        a=_predicted_position(first,t); b=_predicted_position(second,t)
        d=((a[0]-b[0])**2+(a[1]-b[1])**2)**0.5
        if d<best: best,best_t,best_points=d,t,(a,b)
    return (best < clearance_local, best, best_t, best_points)

@app.post("/api/swarm/conflicts/check")
def swarm_check_conflicts():
    active = [v for v in fleet.values() if not v.failed and v.target_x is not None and v.target_y is not None
              and v.status in ("moving", "returning")]
    found = []
    for i, first in enumerate(active):
        for second in active[i+1:]:
            conflict,separation,eta,points=_time_synchronized_conflict(first,second)
            if conflict:
                conflict_data = {"vehicle_ids":[first.id,second.id],
                    "trajectories":[{"start":{"x":first.x,"y":first.y},"end":{"x":first.target_x,"y":first.target_y}},
                                    {"start":{"x":second.x,"y":second.y},"end":{"x":second.target_x,"y":second.target_y}}],
                    "minimum_separation_local":round(separation,3),
                    "minimum_separation_m":round(separation*20.0,1),
                    "predicted_time_to_closest_approach_s":round(eta,2),
                    "predicted_positions":[{"x":round(p[0],3),"y":round(p[1],3)} for p in points]}
                found.append(conflict_data)
                message = swarm.publish("coordinator", "ROUTE_CONFLICT", conflict_data, [first.id,second.id])
                swarm.knowledge["route_conflicts"].insert(0, {**conflict_data, "timestamp":datetime.now(timezone.utc).isoformat(), "message_status":message["status"]})
                del swarm.knowledge["route_conflicts"][50:]
    log("Swarm Coordinator", f"Time-synchronized trajectory scan found {len(found)} predicted conflict(s)")
    persist()
    return {"conflicts":found, "count":len(found), "note":"Predicts synchronized closest approach over a 45-second horizon using current speed and configured acceleration. This remains a simplified 2-D simulator guard, not validated collision avoidance."}

@app.post("/api/fleet/seed")
def seed():
    fleet.clear(); fleet.update(demo_fleet()); orchestrator.missions.clear(); events.clear(); reset_dynamic_obstacles(); swarm.__init__(); swarm.ensure_fleet(fleet); sensor_system.__init__(); sensor_system.ensure_fleet(fleet); swarm.update_link_geometry(fleet, sensor_system.settings); sensor_system.capture_telemetry(fleet,swarm); log("Simulation","Demo fleet, sensor sandbox, blackbox and swarm network reset"); return state()
@app.post("/api/plan")
async def plan(req:PlanRequest):
    m=await orchestrator.plan(req.instruction,fleet,events); persist(); return m
@app.post("/api/missions/{mid}/approve")
def approve(mid:str):
    m=next((x for x in orchestrator.missions if x["id"]==mid),None)
    if not m: raise HTTPException(404,"Mission not found")
    if m["status"]!="PENDING_APPROVAL": raise HTTPException(409,"Mission is not pending approval")
    if not swarm.config["enabled"] or not swarm.config["coordinator_link_enabled"]:
        raise HTTPException(409,"Operator/coordinator link is unavailable; restore the link before approving or dispatching a mission")
    byid={v.id:v.public() for v in fleet.values()}
    checked,errors=orchestrator.safety.validate(m["actions"],byid)
    if errors:
        m["status"]="REJECTED"; m.setdefault("checks",[]).extend(["Approval-time revalidation failed",*errors])
        log("Safety & Policy",f"Mission {mid} rejected at approval because fleet state changed")
        raise HTTPException(409,"Mission failed approval-time safety revalidation: "+"; ".join(errors))
    for a in checked:
        if a.get("action") == "return_home":
            for other in orchestrator.missions:
                if other is not m and other.get("status") == "EXECUTING" and any(x.get("vehicle_id") == a["vehicle_id"] for x in other.get("actions", [])):
                    other["status"] = "DEGRADED"
                    other["failure_reason"] = "Preempted by operator-approved low-battery return-home recovery"
        adapter.dispatch(fleet[a["vehicle_id"]],a)
        swarm.announce_intent(a["vehicle_id"], a)
    m["actions"]=checked
    m["status"]="EXECUTING"
    if m.get("parent_mission_id"):
        parent=next((x for x in orchestrator.missions if x["id"]==m["parent_mission_id"]),None)
        if parent: parent["status"]="RECOVERING"; parent["recovery_mission_id"]=m["id"]
    log("Execution Agent",f"Approved mission {mid} dispatched to simulator"); persist(); return m
@app.post("/api/missions/{mid}/reject")
def reject(mid:str):
    m=next((x for x in orchestrator.missions if x["id"]==mid),None)
    if not m: raise HTTPException(404,"Mission not found")
    if m["status"]!="PENDING_APPROVAL": raise HTTPException(409,"Mission is not pending")
    if not swarm.config["enabled"] or not swarm.config["coordinator_link_enabled"]:
        raise HTTPException(409,"Operator/coordinator link is unavailable; restore the link before approving or rejecting a mission")
    m["status"]="REJECTED"; log("Human Operator",f"Mission {mid} rejected"); persist(); return m
@app.post("/api/vehicles/{vid}/fail")
async def inject_failure(vid:str):
    v=fleet.get(vid)
    if not v: raise HTTPException(404,"Vehicle not found")
    v.failed=True; v.status="failed"; v.target_x=v.target_y=None; v.route_queue=[]; v.speed=0
    swarm.publish("coordinator", "EMERGENCY_ALERT", {"vehicle_id":vid,"vehicle_name":v.name,"event":"vehicle_unavailable","status":"failed"})
    log("Scenario Engine",f"Injected failure: {v.name} is unavailable")
    degraded=[]
    for m in orchestrator.missions:
        if m["status"]=="EXECUTING" and any(a["vehicle_id"]==vid for a in m["actions"]):
            m["status"]="DEGRADED"; m["failure_reason"]=f"{v.name} unavailable"; degraded.append(m)
    recoveries=[]
    for m in degraded:
        recovery_actions=[]
        for a in m["actions"]:
            if a["vehicle_id"]!=vid or a["action"] not in ("goto", "coverage"): continue
            required_type = "area_coverage" if a["action"] == "coverage" else a.get("mission_type", "patrol")
            failed_domain = "air" if v.kind in ("quadrotor", "fixed-wing") else "ground"
            candidates=[x for x in fleet.values() if x.id!=vid and not x.failed
                        and x.status in ("ready","holding") and "navigation" in x.capabilities
                        and required_type in (x.mission_types or [])
                        and (required_type == "area_coverage" or ("air" if x.kind in ("quadrotor", "fixed-wing") else "ground") == failed_domain)
                        and x.battery_pct >= 20]
            candidates.sort(key=lambda x:((x.x-v.x)**2+(x.y-v.y)**2))
            if candidates:
                alt=candidates[0]; recovery_actions.append({"vehicle_id":alt.id,"vehicle_name":alt.name,"action":a["action"],"x":a["x"],"y":a["y"],**({"route_points":a["route_points"]} if a.get("route_points") else {}),"note":f"Recovery reassignment from {v.name}"})
        recovery={"id":str(__import__('uuid').uuid4())[:8],"instruction":f"Recovery for mission {m['id']}: reassign failed vehicle task","status":"PENDING_APPROVAL" if recovery_actions else "RECOVERY_UNAVAILABLE","actions":recovery_actions,
          "checks":["Failure detected","Alternative vehicle capability checked","Human approval required"],"agent_trace":["Mission Monitor: detected vehicle failure and marked mission degraded","Recovery Planner: proposed compatible alternate vehicle","Safety & Policy: recovery awaits human approval"],"provider":"deterministic-recovery","created_at":datetime.now(timezone.utc).isoformat(),"parent_mission_id":m["id"]}
        orchestrator.missions.insert(0,recovery); recoveries.append(recovery)
    log("Mission Monitor",f"Failure analysis complete; {len(recoveries)} recovery proposal(s) created"); persist()
    return {"vehicle":v.public(),"degraded_missions":[m["id"] for m in degraded],"recovery_proposals":recoveries}
def create_low_battery_recovery_proposals():
    """Create operator-approved return-home or emergency-land proposals below 20%."""
    created=[]
    for vehicle in fleet.values():
        if vehicle.failed or vehicle.status in ("failed", "landed") or vehicle.battery_pct >= 20:
            continue
        existing = any(m.get("recovery_vehicle_id")==vehicle.id and m.get("status") in ("PENDING_APPROVAL", "EXECUTING")
                       for m in orchestrator.missions)
        if existing:
            continue
        return_action={"vehicle_id":vehicle.id,"vehicle_name":vehicle.name,"action":"return_home",
                       "note":"Low-battery return-home recommendation; operator approval required"}
        checked, errors = orchestrator.safety.validate([return_action], {v.id:v.public() for v in fleet.values()})
        emergency_action=None; emergency_errors=[]
        if errors:
            # If an aircraft cannot safely make it home, request a local landing.
            # Ground robots use a safe stationary stop because they have no
            # airborne landing capability. Both remain operator-approved.
            fallback_action = "land" if "land" in vehicle.capabilities else "hold"
            emergency_action={"vehicle_id":vehicle.id,"vehicle_name":vehicle.name,"action":fallback_action,
                              "emergency_recovery":True,
                              "note":("Emergency landing at current safe location" if fallback_action=="land"
                                      else "Emergency safe-stop at current location")}
            checked, emergency_errors=orchestrator.safety.validate([emergency_action], {v.id:v.public() for v in fleet.values()})
        emergency_recovery=bool(emergency_action)
        proposal_valid = bool(checked) and not emergency_errors
        return_errors=list(errors)
        mission={"id":str(__import__('uuid').uuid4())[:8],
            "instruction":f"{'Emergency '+emergency_action['action'] if emergency_recovery else 'Low-battery return-home'} recovery for {vehicle.name}",
            "status":"PENDING_APPROVAL" if proposal_valid else "RECOVERY_UNAVAILABLE",
            "actions":checked,"checks":["Battery below 20% threshold","Return-home energy and route safety evaluated",
                "Emergency landing or ground safe-stop selected when protected return reserve is unavailable","Human approval required",
                *( ["Return-home infeasible: "+"; ".join(return_errors)] if return_errors else []), *emergency_errors],
            "agent_trace":["Battery Monitor: low-energy threshold reached",
                "Recovery Planner: evaluated safe return route and protected landing reserve",
                "Safety & Policy: operator approval required before recovery execution"],
            "provider":"deterministic-battery-recovery","created_at":datetime.now(timezone.utc).isoformat(),
            "recovery_vehicle_id":vehicle.id,"emergency_recovery":emergency_recovery}
        orchestrator.missions.insert(0,mission); created.append(mission)
        recovery_label=("Emergency "+emergency_action["action"] if emergency_recovery else "Return-home")
        log("Battery Monitor",f"{recovery_label} proposal created for {vehicle.name}")
    return created

@app.post("/api/simulation/tick")
def sim_tick():
    advance_dynamic_obstacles(1.0, [(v.x,v.y) for v in fleet.values() if not v.failed])
    tick(fleet, dynamic_obstacle_polygons=dynamic_obstacle_polygons())
    swarm.sync_fleet(fleet)
    process_pending_coordination()
    new_observations = sensor_system.scan(fleet, swarm)
    process_sensor_automation(new_observations)
    create_low_battery_recovery_proposals()
    sensor_system.capture_telemetry(fleet, swarm)
    for m in orchestrator.missions:
        if m["status"] in ("EXECUTING","RECOVERING"):
            if m["status"]=="EXECUTING":
                status=orchestrator.monitor.evaluate(m,fleet)
                if status=="COMPLETED": m["status"]="COMPLETED"; log("Mission Monitor",f"Mission {m['id']} completed")
                elif status=="DEGRADED": m["status"]="DEGRADED"
            elif m["status"]=="RECOVERING":
                recovery=next((x for x in orchestrator.missions if x.get("id")==m.get("recovery_mission_id")),None)
                if recovery and recovery["status"]=="COMPLETED": m["status"]="COMPLETED"; log("Mission Monitor",f"Parent mission {m['id']} completed after recovery")
    persist(); return state()
