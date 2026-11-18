from datetime import datetime, timezone
from uuid import uuid4
import os, json, httpx
from .geospatial import in_geofence, in_no_go_zone, in_obstacle, plan_safe_route, segment_is_safe, THEATRE_WIDTH_M

# Matches the simulation's full-speed draw (0.03 battery percentage points/s)
# with a 30% planning contingency and a protected 5% landing reserve.
BATTERY_RESERVE_PCT = 5.0
BATTERY_CONTINGENCY = 1.30
BATTERY_BASE_DRAIN_PCT_PER_SECOND = 0.018
BATTERY_SPEED_DRAIN_PCT_PER_SECOND = 0.012

def _route_distance_m(start, route):
    cursor=(float(start[0]),float(start[1])); total=0.0
    for point in route:
        nxt=(float(point["x"]),float(point["y"]))
        total += ((nxt[0]-cursor[0])**2+(nxt[1]-cursor[1])**2)**0.5 * (THEATRE_WIDTH_M/100.0)
        cursor=nxt
    return total

def _required_battery_pct(vehicle, route):
    """Estimate route energy with acceleration, cruise and a protected reserve.

    The simulator resets speed at each waypoint, so every leg is evaluated
    independently. A 30% contingency covers turn/stop overhead and the
    simplified battery model; this is a planning estimate, not a physical
    battery model.
    """
    max_speed=max(float(vehicle.get("max_speed_mps",1)),0.1)
    accel=max(float(vehicle.get("max_accel",1.0)),0.0)
    cursor=(float(vehicle["x"]),float(vehicle["y"]))
    total_energy=0.0
    metres_per_unit=THEATRE_WIDTH_M/100.0
    for point in route:
        nxt=(float(point["x"]),float(point["y"]))
        distance=(((nxt[0]-cursor[0])**2+(nxt[1]-cursor[1])**2)**0.5)*metres_per_unit
        if distance <= 1e-9:
            cursor=nxt
            continue
        if accel <= 1e-9:
            seconds=distance/max_speed
        else:
            accelerate_distance=(max_speed*max_speed)/(2.0*accel)
            if distance <= accelerate_distance:
                seconds=(2.0*distance/accel)**0.5
            else:
                accelerate_time=max_speed/accel
                seconds=accelerate_time+(distance-accelerate_distance)/max_speed
        # Integrate the simulator's draw formula: base drain per second plus
        # a speed-proportional component over travelled distance.
        total_energy += (BATTERY_BASE_DRAIN_PCT_PER_SECOND*seconds
                         + BATTERY_SPEED_DRAIN_PCT_PER_SECOND*(distance/max_speed))
        cursor=nxt
    return BATTERY_RESERVE_PCT + total_energy*BATTERY_CONTINGENCY

ALLOWED={"goto","coverage","hold","return_home","land"}

def offline_plan(text, fleet):
    out=[]
    for sentence in text.lower().replace(";", ".").split("."):
        mentions=[]
        for v in fleet:
            for key in (v["name"].lower(),v["id"].lower()):
                pos=sentence.find(key)
                if pos>=0: mentions.append((pos,v)); break
        mentions.sort(key=lambda z:z[0])
        for i,(pos,v) in enumerate(mentions):
            segment=sentence[pos:(mentions[i+1][0] if i+1<len(mentions) else len(sentence))]
            if any(w in segment for w in ["stationary","stay","hold","keep"]): a={"action":"hold"}
            elif "return" in segment or "home" in segment: a={"action":"return_home"}
            elif "land" in segment: a={"action":"land"}
            else:
                x,y=50,80
                if "north" in segment: x,y=50,88
                if "east" in segment: x,y=88,50
                if "west" in segment: x,y=12,50
                if "south" in segment: x,y=50,12
                a={"action":"goto","x":x,"y":y}
            out.append({"vehicle_id":v["id"],**a,"note":"Offline demo intent"})
    return out

async def llm_role(role, instruction, context, fallback):
    provider=os.getenv("AI_PROVIDER","offline").lower(); key=os.getenv("GEMINI_API_KEY","")
    if provider!="gemini" or not key: return fallback,"offline"
    model=os.getenv("GEMINI_MODEL","gemini-2.5-flash")
    prompt=(f"You are the {role} agent in a multi-agent fleet simulation. {instruction}\n"
            f"Return only valid JSON. Context: {json.dumps(context)}")
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    try:
        async with httpx.AsyncClient(timeout=25) as c:
            r=await c.post(url,json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.1,"responseMimeType":"application/json"}})
            r.raise_for_status(); raw=r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(raw),"gemini"
    except Exception as exc:
        return fallback,"offline-fallback:"+type(exc).__name__

async def planner(text,fleet):
    fallback={"actions":offline_plan(text,fleet)}
    result,provider=await llm_role("Mission Planner","Translate operator intent into actions. Schema: {actions:[{vehicle_id,action,x?,y?,note?}]}. Actions: goto, hold, return_home, land. Coordinates 0..100. Use only listed IDs.",{"instruction":text,"fleet":[{"id":v["id"],"name":v["name"],"kind":v["kind"]} for v in fleet]},fallback)
    return result.get("actions",[]) if isinstance(result,dict) else [],provider

class FleetCoordinatorAgent:
    async def coordinate(self, actions, fleet):
        fallback={"actions":actions,"assignments":"Preserved requested vehicle assignments"}
        result,provider=await llm_role("Fleet Coordinator","Review assignments for vehicle capability and compatibility. Do not invent vehicles or change operator intent. Return {actions:[...] , rationale:string}.",{"actions":actions,"fleet":fleet},fallback)
        return result.get("actions",[]) if isinstance(result,dict) else actions,provider,result.get("rationale", "Deterministic assignment review") if isinstance(result,dict) else "Fallback assignment review"

class SafetyPolicyAgent:
    def validate(self, actions, byid):
        errors=[]; accepted=[]
        if not isinstance(actions,list) or not actions: errors.append("Planner returned no executable actions"); return accepted,errors
        if len(actions)>10: errors.append("Mission exceeds the 10-action demo limit"); return accepted,errors
        for item in actions:
            if not isinstance(item,dict): errors.append("Malformed action object"); continue
            error_count = len(errors)
            a=dict(item); v=byid.get(a.get("vehicle_id"))
            if not v: errors.append(f"Unknown vehicle: {a.get('vehicle_id')}"); continue
            a["vehicle_name"]=v["name"]; k=a.get("action")
            if k not in ALLOWED: errors.append(f"{v['name']}: action not allowlisted"); continue
            emergency_stop = k in ("land", "hold") and bool(a.get("emergency_recovery")) and (v["status"] == "low_battery" or float(v.get("battery_pct", 100)) < 20)
            if v["status"] not in ("ready","holding") and not (k == "return_home" and v["status"] in ("moving","returning","low_battery")) and not emergency_stop:
                errors.append(f"{v['name']}: vehicle unavailable")
            if k in ("goto", "coverage"):
                if "navigation" not in v["capabilities"]: errors.append(f"{v['name']}: navigation unsupported")
                if k == "coverage" and "area_coverage" not in v.get("mission_types", []): errors.append(f"{v['name']}: area coverage mission capability unavailable")
                if not all(isinstance(a.get(q),(int,float)) and 0<=a[q]<=100 for q in ("x","y")):
                    errors.append(f"{v['name']}: coordinates must be 0..100")
                elif not in_geofence(float(a["x"]), float(a["y"])):
                    errors.append(f"{v['name']}: waypoint is outside the operating geofence")
                elif in_no_go_zone(float(a["x"]), float(a["y"])):
                    errors.append(f"{v['name']}: waypoint intersects a restricted no-go zone")
                elif in_obstacle(float(a["x"]), float(a["y"])):
                    errors.append(f"{v['name']}: waypoint is inside a simulated obstacle")
                elif k == "goto":
                    try:
                        route = plan_safe_route((float(v["x"]), float(v["y"])), (float(a["x"]), float(a["y"])))
                        a["route_points"] = route
                        required_battery = _required_battery_pct(v, route)
                        if float(v.get("battery_pct", 0)) < required_battery:
                            errors.append(f"{v['name']}: insufficient battery for route plus protected landing reserve (requires approximately {required_battery:.1f}%)")
                    except ValueError as exc:
                        errors.append(f"{v['name']}: {exc}")
            if k == "coverage":
                    route = a.get("route_points")
                    if not isinstance(route, list) or not route or len(route) > 120:
                        errors.append(f"{v['name']}: coverage route must contain 1..120 waypoints")
                    else:
                        for point in route:
                            if not isinstance(point, dict) or not all(isinstance(point.get(q),(int,float)) and 0 <= point[q] <= 100 for q in ("x","y")):
                                errors.append(f"{v['name']}: malformed coverage waypoint"); break
                            if not in_geofence(float(point["x"]), float(point["y"])) or in_no_go_zone(float(point["x"]), float(point["y"])):
                                errors.append(f"{v['name']}: coverage route violates geofence or restricted zone"); break
                        if not any("coverage route" in e or "malformed coverage" in e for e in errors[error_count:]):
                            expanded=[]; cursor=(float(v["x"]),float(v["y"]))
                            try:
                                for point in route:
                                    leg=plan_safe_route(cursor,(float(point["x"]),float(point["y"])))
                                    expanded.extend(leg); cursor=(float(point["x"]),float(point["y"]))
                                a["route_points"]=expanded
                                required_battery = _required_battery_pct(v, expanded)
                                if float(v.get("battery_pct", 0)) < required_battery:
                                    errors.append(f"{v['name']}: insufficient battery for coverage route plus protected landing reserve (requires approximately {required_battery:.1f}%)")
                            except ValueError as exc:
                                errors.append(f"{v['name']}: coverage route cannot be safely connected: {exc}")
            if k == "return_home":
                try:
                    a["route_points"] = plan_safe_route((float(v["x"]),float(v["y"])),
                                                         (float(v.get("home_x",10)),float(v.get("home_y",10))))
                    required_battery = _required_battery_pct(v, a["route_points"])
                    if float(v.get("battery_pct", 0)) < required_battery:
                        errors.append(f"{v['name']}: cannot safely return home; route requires approximately {required_battery:.1f}% including contingency and 5% landing reserve")
                except ValueError as exc:
                    errors.append(f"{v['name']}: return-home route unavailable: {exc}")
            if k in ("land", "hold") and a.get("emergency_recovery"):
                if not in_geofence(float(v["x"]),float(v["y"])) or in_no_go_zone(float(v["x"]),float(v["y"])) or in_obstacle(float(v["x"]),float(v["y"])):
                    errors.append(f"{v['name']}: emergency stop point is not a safe demo-theatre location")
            if k in ("hold","return_home","land") and k not in v["capabilities"]: errors.append(f"{v['name']}: {k} capability unavailable")
            if len(errors) == error_count:
                accepted.append(a)
        # Two tasks cannot safely finish within the simulator's minimum
        # vehicle-separation radius. Reject impossible plans before approval.
        endpoints=[]
        for action in accepted:
            vehicle=byid[action["vehicle_id"]]
            kind=action.get("action")
            if kind in ("goto","coverage"):
                route=action.get("route_points") or [{"x":action.get("x"),"y":action.get("y")}]
                if route and isinstance(route[-1],dict) and isinstance(route[-1].get("x"),(int,float)) and isinstance(route[-1].get("y"),(int,float)):
                    endpoints.append((action["vehicle_id"],(float(route[-1]["x"]),float(route[-1]["y"]))))
            elif kind == "return_home":
                endpoints.append((action["vehicle_id"],(float(vehicle.get("home_x",10)),float(vehicle.get("home_y",10)))))
            elif kind in ("hold","land"):
                endpoints.append((action["vehicle_id"],(float(vehicle["x"]),float(vehicle["y"]))))
        for index,(first_id,first_point) in enumerate(endpoints):
            for second_id,second_point in endpoints[index+1:]:
                if first_id == second_id:
                    continue
                if ((first_point[0]-second_point[0])**2+(first_point[1]-second_point[1])**2)**0.5 < 2.0-1e-6:
                    errors.append(f"{first_id} and {second_id}: planned end positions violate the 2-local-unit minimum vehicle separation")
        # A multi-vehicle plan is an atomic proposal: if any action or pairwise
        # endpoint constraint fails, return no executable actions. Callers still
        # receive the complete error list for the rejected proposal.
        return ([],errors) if errors else (accepted,errors)

class MissionMonitorAgent:
    def evaluate(self, mission, fleet):
        actions=mission.get("actions",[])
        vehicles=[fleet.get(a["vehicle_id"]) for a in actions]
        if any(v is None or v.failed or v.status in ("failed","low_battery") for v in vehicles):
            return "DEGRADED"
        terminal={"goto":"ready","coverage":"ready","return_home":"ready",
                  "hold":"holding","land":"landed"}
        for action,vehicle in zip(actions,vehicles):
            expected=terminal.get(action.get("action"))
            if expected is None:
                return "DEGRADED"
            if vehicle.status in ("moving","returning"):
                return mission["status"]
            if vehicle.status != expected:
                # A vehicle which stopped, landed or yielded before reaching its
                # assigned goal must not be reported as a completed mission.
                return "DEGRADED"
        return "COMPLETED" if vehicles else "DEGRADED"

class AgentOrchestrator:
    def __init__(self): self.missions=[]; self.coordinator=FleetCoordinatorAgent(); self.safety=SafetyPolicyAgent(); self.monitor=MissionMonitorAgent()
    async def plan(self,text,fleet,events):
        roster=[v.public() for v in fleet.values()]
        raw,provider=await planner(text,roster)
        trace=["Mission Planner: produced structured operator-intent proposal"]
        coordinated,coord_provider,rationale=await self.coordinator.coordinate(raw,roster)
        def intent_signature(items):
            return sorted((x.get("vehicle_id"),x.get("action"),x.get("x"),x.get("y")) for x in items if isinstance(x,dict))
        if not isinstance(coordinated,list) or intent_signature(coordinated)!=intent_signature(raw):
            coordinated=raw
            rationale="Coordinator output changed the planner intent; original proposal preserved"
        trace.append("Fleet Coordinator: reviewed assignments — "+rationale)
        byid={v["id"]:v for v in roster}; actions,errors=self.safety.validate(coordinated,byid)
        trace.append("Safety & Policy: "+("all deterministic checks passed" if not errors else "proposal rejected by policy"))
        m={"id":str(uuid4())[:8],"instruction":text,"status":"PENDING_APPROVAL" if not errors else "REJECTED","actions":actions,
           "checks":["Allowlist","Identity","Availability","Capabilities","Coordinate bounds","Geofence"]+errors,
           "agent_trace":trace,"provider":provider,"coordinator_provider":coord_provider,"created_at":datetime.now(timezone.utc).isoformat()}
        self.missions.insert(0,m); events.append({"time":m["created_at"],"agent":"Agent Orchestrator","message":f"Mission {m['id']} {m['status']}"})
        for x in trace: events.append({"time":m["created_at"],"agent":"Multi-agent workflow","message":x})
        return m
