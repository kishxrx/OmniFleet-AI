from dataclasses import dataclass, asdict
import math
from .geospatial import THEATRE_WIDTH_M, plan_safe_route

@dataclass
class Vehicle:
    id: str; name: str; kind: str; x: float; y: float; altitude_m: float
    battery_pct: float; status: str; max_speed_mps: float; capabilities: list
    home_x: float = 10; home_y: float = 10
    target_x: float | None = None; target_y: float | None = None
    speed: float = 0.0; heading_deg: float = 0.0; max_accel: float = 1.5
    climb_rate_mps: float = 2.0; failed: bool = False
    route_queue: list = None
    mission_types: list = None
    blocked_ticks: int = 0
    def public(self): return asdict(self)

def demo_fleet():
    return {
      "scout-1": Vehicle("scout-1","Scout-1","quadrotor",18,25,25,94,"ready",4,["navigation","hold","return_home","land"], max_accel=2.0, mission_types=["patrol","inspect","area_coverage"]),
      "scout-2": Vehicle("scout-2","Scout-2","fixed-wing",45,60,60,81,"ready",6,["navigation","return_home","land"], max_accel=1.2, mission_types=["patrol","inspect","area_coverage"]),
      "relay-1": Vehicle("relay-1","Relay-1","ground_robot",70,48,0,88,"ready",2,["navigation","hold","return_home"], max_accel=1.0, climb_rate_mps=0, mission_types=["patrol","ground_inspection","area_coverage"]),
    }

def vehicle_from_dict(d):
    d = dict(d)
    d.setdefault("route_queue", None)
    d.setdefault("mission_types", ["patrol", "inspect", "area_coverage"] if d.get("kind") in ("quadrotor", "fixed-wing") else ["patrol", "ground_inspection", "area_coverage"])
    d.setdefault("blocked_ticks", 0)
    return Vehicle(**d)

def dispatch(v, a):
    k=a["action"]
    if k in ("goto", "coverage"):
        route = a.get("route_points") or [{"x": a["x"], "y": a["y"]}]
        v.route_queue = list(route[1:])
        v.target_x,v.target_y=route[0]["x"],route[0]["y"]; v.status="moving"; v.blocked_ticks=0
    elif k=="hold": v.target_x=v.target_y=None; v.route_queue=[]; v.speed=0; v.status="holding"; v.blocked_ticks=0
    elif k=="return_home":
        route = a.get("route_points") or [{"x": v.home_x, "y": v.home_y}]
        v.route_queue = list(route[1:]); v.target_x,v.target_y=route[0]["x"],route[0]["y"]; v.status="returning"; v.blocked_ticks=0
    elif k=="land": v.target_x=v.target_y=None; v.route_queue=[]; v.speed=0; v.altitude_m=0; v.status="landed"; v.blocked_ticks=0
    return {"vehicle_id":v.id,"action":k,"result":"accepted"}

def _point_segment_distance(p, a, b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    if dx==0 and dy==0: return math.hypot(p[0]-a[0],p[1]-a[1])
    t=max(0.0,min(1.0,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(p[0]-(a[0]+t*dx),p[1]-(a[1]+t*dy))

def _segments_too_close(a,b,c,d,clearance=2.0):
    orient=lambda p,q,r:(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    if o1*o2<=0 and o3*o4<=0: return True
    return min(_point_segment_distance(a,c,d),_point_segment_distance(b,c,d),
               _point_segment_distance(c,a,b),_point_segment_distance(d,a,b))<clearance

def _synchronous_closest_approach(a0, a1, b0, b1):
    """Minimum separation for two linear movements over the same time interval."""
    rx, ry = a0[0] - b0[0], a0[1] - b0[1]
    avx, avy = a1[0] - a0[0], a1[1] - a0[1]
    bvx, bvy = b1[0] - b0[0], b1[1] - b0[1]
    vx, vy = avx - bvx, avy - bvy
    denom = vx * vx + vy * vy
    t = 0.0 if denom <= 1e-12 else max(0.0, min(1.0, -(rx * vx + ry * vy) / denom))
    pa = (a0[0] + avx * t, a0[1] + avy * t)
    pb = (b0[0] + bvx * t, b0[1] + bvy * t)
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1]), t


def _route_around_peer(start, goal, peer, clearance=2.0):
    """Find a conservative polyline around a stationary peer position."""
    from .geospatial import segment_is_safe, in_geofence, plan_safe_route
    start=tuple(map(float,start)); goal=tuple(map(float,goal)); peer=tuple(map(float,peer))
    if math.hypot(goal[0]-peer[0],goal[1]-peer[1]) < clearance-1e-6:
        return None
    try:
        direct=plan_safe_route(start,goal)
    except ValueError:
        direct=None
    def clear(route):
        cursor=start
        for point in route:
            nxt=(float(point["x"]),float(point["y"]))
            initial=math.hypot(cursor[0]-peer[0],cursor[1]-peer[1])
            final=math.hypot(nxt[0]-peer[0],nxt[1]-peer[1])
            move=(nxt[0]-cursor[0],nxt[1]-cursor[1])
            away=(cursor[0]-peer[0])*move[0]+(cursor[1]-peer[1])*move[1]
            recovering=initial < clearance and final > initial+1e-6 and away >= -1e-9
            if not recovering and _point_segment_distance(peer,cursor,nxt) < clearance-1e-6:
                return False
            if not segment_is_safe(cursor,nxt):
                return False
            cursor=nxt
        return True
    if direct and clear(direct):
        return direct

    # A polyline with a lateral offset is robust when start and goal lie on
    # opposite sides of a stationary peer. It avoids the chord-cutting problem
    # of trying to approximate a circular arc with a single diagonal segment.
    dx,dy=goal[0]-peer[0],goal[1]-peer[1]
    distance=math.hypot(dx,dy)
    if distance <= 1e-9:
        return None
    px,py=-dy/distance,dx/distance
    for side in (1.0,-1.0):
        for offset in (clearance+0.15, clearance+0.75, clearance+1.5, clearance+3.0):
            lateral=(px*side*offset,py*side*offset)
            route=[{"x":start[0]+lateral[0],"y":start[1]+lateral[1]},
                   {"x":goal[0]+lateral[0],"y":goal[1]+lateral[1]},
                   {"x":goal[0],"y":goal[1]}]
            if all(in_geofence(float(p["x"]),float(p["y"])) for p in route) and clear(route):
                return route
    # Try the visibility-graph route through a lateral approach to the goal.
    for side in (1.0,-1.0):
        for offset in (clearance+0.15, clearance+0.75, clearance+1.5, clearance+3.0):
            approach=(goal[0]+px*offset*side,goal[1]+py*offset*side)
            if not in_geofence(*approach):
                continue
            try:
                first_leg=plan_safe_route(start,approach)
            except ValueError:
                continue
            candidate=[*first_leg,{"x":goal[0],"y":goal[1]}]
            if clear(candidate):
                return candidate
    return None


def _schedule_vehicle_avoidance(vehicle, stationary_vehicle):
    """Insert a safe temporary sidestep before resuming the vehicle's goal leg."""
    from .geospatial import in_geofence, plan_safe_route, segment_is_safe
    goal=(vehicle.target_x,vehicle.target_y)
    if goal[0] is None or goal[1] is None:
        return False
    dx,dy=goal[0]-vehicle.x,goal[1]-vehicle.y
    length=math.hypot(dx,dy)
    if length<=1e-9:
        return False
    # Candidate sidesteps around the yielding vehicle. Try both sides and
    # increasing clearances; the route planner still enforces geo-fences,
    # restricted zones, static obstacles and the current moving obstacle.
    ux,uy=dx/length,dy/length
    directions=[(-ux+1.5*(-uy),-uy+1.5*ux),
                (-ux-1.5*(-uy),-uy-1.5*ux),
                (-ux+2.0*(-uy),-uy+2.0*ux),
                (-ux-2.0*(-uy),-uy-2.0*ux),
                (-uy,ux),(uy,-ux)]
    normalized=[]
    for vx,vy in directions:
        norm=math.hypot(vx,vy)
        if norm>1e-9: normalized.append((vx/norm,vy/norm))
    directions=normalized
    original_goal={"x":float(goal[0]),"y":float(goal[1])}
    peer=(stationary_vehicle.x,stationary_vehicle.y)
    current_separation=math.hypot(vehicle.x-peer[0],vehicle.y-peer[1])
    goal_separation=math.hypot(goal[0]-peer[0],goal[1]-peer[1])
    # Once this vehicle has cleared the peer, do not invent another detour
    # toward a target still occupied by that peer. Hold until it moves away.
    if current_separation > 2.25 and goal_separation < 2.0-1e-6:
        return False
    for radius in (3.0,4.0,5.0,6.0,7.0):
        for vx,vy in directions:
            candidate=(peer[0]+vx*radius,peer[1]+vy*radius)
            if not in_geofence(*candidate):
                continue
            try:
                sidestep=plan_safe_route((vehicle.x,vehicle.y),candidate)
                continuation=(_route_around_peer(candidate,goal,peer,2.0)
                              if goal_separation >= 2.0-1e-6 else
                              [{"x":float(goal[0]),"y":float(goal[1])}])
                if continuation is None:
                    continue
            except ValueError:
                continue
            cursor=(vehicle.x,vehicle.y); clear=True
            # The first leg must clear the peer's current position. When the
            # vehicles already overlap, permit a strictly separating first
            # movement; otherwise the collision guard could never recover.
            # The continuation may pass the peer's current cell later, after
            # that peer has moved, so it is validated on subsequent ticks.
            for point in sidestep:
                nxt=(float(point["x"]),float(point["y"]))
                start_sep=math.hypot(cursor[0]-peer[0],cursor[1]-peer[1])
                end_sep=math.hypot(nxt[0]-peer[0],nxt[1]-peer[1])
                move_x,move_y=nxt[0]-cursor[0],nxt[1]-cursor[1]
                away_dot=(cursor[0]-peer[0])*move_x+(cursor[1]-peer[1])*move_y
                if start_sep < 2.0 and end_sep > start_sep+1e-6 and away_dot >= -1e-9:
                    cursor=nxt
                    continue
                if _point_segment_distance(peer,cursor,nxt)<2.0-1e-6:
                    clear=False; break
                cursor=nxt
            if not clear or not sidestep:
                continue
            combined=[*sidestep,*continuation]
            if not combined:
                continue
            vehicle.target_x=float(combined[0]["x"]); vehicle.target_y=float(combined[0]["y"])
            vehicle.route_queue=[{"x":float(p["x"]),"y":float(p["y"])} for p in combined[1:]]
            vehicle.speed=0.0
            return True
    return False


def tick(fleet, dt=1.0, dynamic_obstacle_polygons=None, minimum_separation_local=2.0):
    """Advance bounded 2-D kinematics with synchronized collision avoidance.

    Conflicting motion is resolved conservatively. A deterministic vehicle may
    advance only to the safe separation boundary; the yielding vehicle then
    receives a lateral route around the stationary peer. If no safe path exists,
    vehicles wait and eventually enter a safe hold, degrading the mission rather
    than interpenetrating or remaining EXECUTING forever.
    """
    dt=max(0.0,min(float(dt),2.0))
    metres_per_unit=THEATRE_WIDTH_M/100.0
    starts={vid:(float(v.x),float(v.y)) for vid,v in fleet.items()}
    proposals={}
    for vid,v in fleet.items():
        if v.failed or v.target_x is None or v.target_y is None or v.status not in ("moving","returning"):
            continue
        dx,dy=v.target_x-v.x,v.target_y-v.y
        distance_local=math.hypot(dx,dy); distance_m=distance_local*metres_per_unit
        desired=min(v.max_speed_mps,math.sqrt(max(0.0,2*v.max_accel*distance_m)))
        next_speed=max(0.0,v.speed+max(-v.max_accel*dt,min(v.max_accel*dt,desired-v.speed)))
        step_m=min(distance_m,next_speed*dt); step_local=step_m/metres_per_unit
        if distance_local>1e-9:
            nx=v.x+dx/distance_local*step_local; ny=v.y+dy/distance_local*step_local
            v.heading_deg=(math.degrees(math.atan2(dx,dy))+360)%360
        else:
            nx,ny=v.x,v.y
        proposals[vid]=(nx,ny,next_speed,step_m>=distance_m-1e-9)

    blocked=set(); dynamic_blocked=set(); rerouted=set(); blocked_by_peer={}
    moving_ids=sorted(proposals)

    def assign_peer_detour(vehicle, peer):
        goal=(float(vehicle.target_x),float(vehicle.target_y))
        route=_route_around_peer((vehicle.x,vehicle.y),goal,(peer.x,peer.y),minimum_separation_local)
        if not route:
            return False
        old_queue=list(vehicle.route_queue or [])
        vehicle.target_x=float(route[0]["x"]); vehicle.target_y=float(route[0]["y"])
        vehicle.route_queue=[*route[1:],*old_queue]
        vehicle.speed=0.0; vehicle.blocked_ticks=0
        return True

    # Resolve simultaneous movers. If only one path clears the other's current
    # position, it gets right-of-way. If neither clears, one advances only to the
    # separation boundary, then the other is routed laterally on the next tick.
    for index,first_id in enumerate(moving_ids):
        for second_id in moving_ids[index+1:]:
            first_start,second_start=starts[first_id],starts[second_id]
            first_end,second_end=proposals[first_id][:2],proposals[second_id][:2]
            dx=first_start[0]-second_start[0]; dy=first_start[1]-second_start[1]
            initial_sep=math.hypot(dx,dy)
            first_delta=(first_end[0]-first_start[0],first_end[1]-first_start[1])
            second_delta=(second_end[0]-second_start[0],second_end[1]-second_start[1])
            relative_dot=dx*(first_delta[0]-second_delta[0])+dy*(first_delta[1]-second_delta[1])
            recovering_overlap=initial_sep<minimum_separation_local and relative_dot>=-1e-9
            closest,_=_synchronous_closest_approach(first_start,first_end,second_start,second_end)
            if closest>=minimum_separation_local or recovering_overlap:
                continue
            first_clears=_point_segment_distance(second_start,first_start,first_end)>=minimum_separation_local-1e-6
            second_clears=_point_segment_distance(first_start,second_start,second_end)>=minimum_separation_local-1e-6
            if first_clears and not second_clears:
                blocked.add(second_id); blocked_by_peer[second_id]=first_id
            elif second_clears and not first_clears:
                blocked.add(first_id); blocked_by_peer[first_id]=second_id
            elif first_clears and second_clears:
                blocked.add(second_id); blocked_by_peer[second_id]=first_id
            elif initial_sep>minimum_separation_local+1e-6:
                # Clip the deterministic winner's proposal to the boundary of
                # the loser's current position rather than allowing it to pass
                # through the occupied point in one large simulation step.
                lo,hi=0.0,1.0
                for _ in range(40):
                    mid=(lo+hi)/2.0
                    point=(first_start[0]+first_delta[0]*mid,first_start[1]+first_delta[1]*mid)
                    if math.hypot(point[0]-second_start[0],point[1]-second_start[1])>=minimum_separation_local:
                        lo=mid
                    else:
                        hi=mid
                if lo>1e-5:
                    point=(first_start[0]+first_delta[0]*lo,first_start[1]+first_delta[1]*lo)
                    proposals[first_id]=(point[0],point[1],proposals[first_id][2],False)
                    blocked.add(second_id); blocked_by_peer[second_id]=first_id
                else:
                    # At the boundary: route the yielding vehicle around the
                    # winner. It starts moving on the following tick.
                    second=fleet[second_id]; first=fleet[first_id]
                    if assign_peer_detour(second,first): rerouted.add(second_id)
                    blocked.update((first_id,second_id))
                    blocked_by_peer[first_id]=second_id; blocked_by_peer[second_id]=first_id
            else:
                # Already at the clearance boundary: keep the priority vehicle
                # stationary for this tick and schedule a lateral detour for the
                # yielding peer. The route becomes active on the next tick.
                second=fleet[second_id]; first=fleet[first_id]
                if assign_peer_detour(second,first):
                    rerouted.add(second_id)
                blocked.update((first_id,second_id))
                blocked_by_peer[first_id]=second_id; blocked_by_peer[second_id]=first_id

    # Re-check movers against vehicles that will remain stationary for this tick.
    changed=True
    while changed:
        changed=False
        stationary_ids=set(fleet)-(set(proposals)-blocked)
        for vid,(nx,ny,_speed,_arrived) in proposals.items():
            if vid in blocked:
                continue
            own_start=starts[vid]
            for other_id in stationary_ids:
                if other_id==vid:
                    continue
                peer_start=starts[other_id]
                initial_sep=math.hypot(own_start[0]-peer_start[0],own_start[1]-peer_start[1])
                end_sep=math.hypot(nx-peer_start[0],ny-peer_start[1])
                move=(nx-own_start[0],ny-own_start[1])
                away=(own_start[0]-peer_start[0])*move[0]+(own_start[1]-peer_start[1])*move[1]
                recovering=initial_sep<minimum_separation_local and end_sep>initial_sep+1e-6 and away>=-1e-9
                if not recovering and _point_segment_distance(peer_start,own_start,(nx,ny))<minimum_separation_local-1e-6:
                    peer=fleet[other_id]
                    # Impossible destination: reject the task by safely holding.
                    destination=(float(fleet[vid].target_x),float(fleet[vid].target_y))
                    if math.hypot(destination[0]-peer.x,destination[1]-peer.y)<minimum_separation_local-1e-6:
                        blocked.add(vid); blocked_by_peer[vid]=other_id
                    elif assign_peer_detour(fleet[vid],peer):
                        blocked.add(vid); rerouted.add(vid); blocked_by_peer[vid]=other_id
                    else:
                        blocked.add(vid); blocked_by_peer[vid]=other_id
                    changed=True; break
            if vid in blocked:
                continue
            for polygon in dynamic_obstacle_polygons or []:
                distance=math.hypot(nx-own_start[0],ny-own_start[1])
                steps=max(1,int(math.ceil(distance/0.2)))
                from .geospatial import point_in_polygon
                if any(point_in_polygon((own_start[0]+(nx-own_start[0])*j/steps,
                                         own_start[1]+(ny-own_start[1])*j/steps),polygon)
                       for j in range(steps+1)):
                    blocked.add(vid); dynamic_blocked.add(vid); changed=True; break

    for vid,(nx,ny,speed,arrived) in proposals.items():
        v=fleet[vid]
        if vid in blocked:
            v.speed=0.0
            if vid in rerouted:
                continue
            if vid in dynamic_blocked and v.target_x is not None and v.target_y is not None:
                try:
                    detour=plan_safe_route((v.x,v.y),(v.target_x,v.target_y))
                    if detour:
                        v.target_x,v.target_y=detour[0]["x"],detour[0]["y"]
                        v.route_queue=list(detour[1:])+list(v.route_queue or [])
                        v.blocked_ticks=0
                    else:
                        v.status="holding"; v.target_x=v.target_y=None; v.route_queue=[]; v.blocked_ticks=0
                except ValueError:
                    v.status="holding"; v.target_x=v.target_y=None; v.route_queue=[]; v.blocked_ticks=0
                continue
            v.blocked_ticks+=1
            peer_id=blocked_by_peer.get(vid); peer=fleet.get(peer_id) if peer_id else None
            if peer and v.target_x is not None and v.target_y is not None:
                target_sep=math.hypot(float(v.target_x)-peer.x,float(v.target_y)-peer.y)
                if target_sep<minimum_separation_local-1e-6 and peer.status not in ("moving","returning"):
                    v.status="holding"; v.target_x=v.target_y=None; v.route_queue=[]; v.speed=0.0
                    continue
            if v.blocked_ticks>=8:
                v.status="holding"; v.target_x=v.target_y=None; v.route_queue=[]; v.speed=0.0
            continue

        v.blocked_ticks=0
        achieved_speed=speed
        v.x,v.y=nx,ny; v.speed=speed
        if arrived:
            v.x,v.y=v.target_x,v.target_y; v.target_x=v.target_y=None; v.speed=0.0
            if v.route_queue:
                nxt=v.route_queue.pop(0); v.target_x,v.target_y=nxt["x"],nxt["y"]
            else:
                v.status="ready"
        if v.kind!="ground_robot" and v.altitude_m>0:
            v.altitude_m=max(0.0,v.altitude_m-0.01*dt)
        v.battery_pct=max(0.0,v.battery_pct-(0.018+0.012*(achieved_speed/max(v.max_speed_mps,0.01)))*dt)
        if v.battery_pct<=5:
            v.status="low_battery"; v.target_x=v.target_y=None; v.route_queue=[]; v.speed=0.0
