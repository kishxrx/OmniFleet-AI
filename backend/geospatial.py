"""WGS84 <-> local tangent-plane helpers for the illustrative demo theatre.

This is a small-area equirectangular approximation, not a navigation-grade
projection. Replace with a surveyed origin and a proper projection for real use.
"""
from __future__ import annotations
import math
import os

EARTH_RADIUS_M = 6_371_008.8
METRES_PER_DEGREE_LAT = 111_320.0
THEATRE_WIDTH_M = float(os.getenv("OMNIFLEET_THEATRE_WIDTH_M", "2000"))
ORIGIN_LAT = float(os.getenv("OMNIFLEET_ORIGIN_LAT", "12.9716"))
ORIGIN_LON = float(os.getenv("OMNIFLEET_ORIGIN_LON", "77.5946"))

# Normalized local grid. The restricted polygon is deliberately separate from
# the permitted operating geofence and is checked server-side.
GEOFENCE = [(4.0, 4.0), (96.0, 4.0), (96.0, 96.0), (4.0, 96.0)]
NO_GO_ZONES = [[(20.0, 62.0), (42.0, 62.0), (42.0, 82.0), (20.0, 82.0)]]
# Fixed virtual structure in the demo theatre; routes must pass around it.
OBSTACLES = [{"id":"structure-1", "label":"Simulated structure", "moving":False,
              "polygon":[(63.0, 66.0), (72.0, 66.0), (72.0, 76.0), (63.0, 76.0)]}]

# Deterministic moving obstacle fixture. The obstacle moves horizontally in a
# bounded lane and pauses/reverses rather than entering a vehicle's occupied cell.
_DYNAMIC_OBSTACLE = {"id":"moving-obstacle-1", "label":"Moving simulated obstacle",
    "cx":54.0, "cy":48.0, "half_w":1.25, "half_h":1.25,
    "min_x":47.0, "max_x":57.0, "speed_units_s":0.12, "direction":-1.0}

def reset_dynamic_obstacles():
    _DYNAMIC_OBSTACLE.update({"cx":54.0, "cy":48.0, "direction":-1.0})

def _moving_obstacle_polygon():
    o=_DYNAMIC_OBSTACLE; x=o["cx"]; y=o["cy"]; w=o["half_w"]; h=o["half_h"]
    return [(x-w,y-h),(x+w,y-h),(x+w,y+h),(x-w,y+h)]

def dynamic_obstacle_polygons():
    return [_moving_obstacle_polygon()]

def dynamic_obstacle_state():
    o=_DYNAMIC_OBSTACLE
    return [{"id":o["id"],"label":o["label"],"moving":True,
             "center":{"x":round(o["cx"],3),"y":round(o["cy"],3)},
             "polygon":[[round(x,3),round(y,3)] for x,y in _moving_obstacle_polygon()]}]

def advance_dynamic_obstacles(dt: float, protected_points=None):
    """Advance the deterministic obstacle, preserving a small vehicle clearance."""
    o=_DYNAMIC_OBSTACLE; previous=o["cx"]
    candidate=previous+o["direction"]*o["speed_units_s"]*max(0.0,min(float(dt),2.0))
    if candidate < o["min_x"] or candidate > o["max_x"]:
        o["direction"] *= -1.0
        candidate=previous+o["direction"]*o["speed_units_s"]*max(0.0,min(float(dt),2.0))
    o["cx"]=candidate
    polygon=_moving_obstacle_polygon()
    if any(point_in_polygon((float(x),float(y)),polygon) or
           min(math.hypot(float(x)-px,float(y)-py) for px,py in polygon)<0.6
           for x,y in (protected_points or [])):
        o["cx"]=previous
        o["direction"] *= -1.0
    return dynamic_obstacle_state()


def local_to_wgs84(x: float, y: float) -> tuple[float, float]:
    half = THEATRE_WIDTH_M / 2.0
    east_m = (float(x) / 100.0 * THEATRE_WIDTH_M) - half
    north_m = (float(y) / 100.0 * THEATRE_WIDTH_M) - half
    lat = ORIGIN_LAT + north_m / METRES_PER_DEGREE_LAT
    lon_scale = METRES_PER_DEGREE_LAT * math.cos(math.radians(ORIGIN_LAT))
    lon = ORIGIN_LON + east_m / lon_scale
    return lat, lon


def wgs84_to_local(lat: float, lon: float) -> tuple[float, float]:
    north_m = (float(lat) - ORIGIN_LAT) * METRES_PER_DEGREE_LAT
    lon_scale = METRES_PER_DEGREE_LAT * math.cos(math.radians(ORIGIN_LAT))
    east_m = (float(lon) - ORIGIN_LON) * lon_scale
    half = THEATRE_WIDTH_M / 2.0
    x = ((east_m + half) / THEATRE_WIDTH_M) * 100.0
    y = ((north_m + half) / THEATRE_WIDTH_M) * 100.0
    return x, y


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside or any(math.hypot(x - px, y - py) < 1e-8 for px, py in polygon)


def in_geofence(x: float, y: float) -> bool:
    return point_in_polygon((x, y), GEOFENCE)


def in_no_go_zone(x: float, y: float) -> bool:
    return any(point_in_polygon((x, y), zone) for zone in NO_GO_ZONES)

def in_obstacle(x: float, y: float) -> bool:
    return (any(point_in_polygon((x, y), obstacle["polygon"]) for obstacle in OBSTACLES)
            or any(point_in_polygon((x, y), polygon) for polygon in dynamic_obstacle_polygons()))


def map_config() -> dict:
    corners = [local_to_wgs84(x, y) for x, y in [(0, 0), (100, 0), (100, 100), (0, 100)]]
    geofence = [local_to_wgs84(x, y) for x, y in GEOFENCE]
    no_go = [[local_to_wgs84(x, y) for x, y in zone] for zone in NO_GO_ZONES]
    return {
        "origin": {"lat": ORIGIN_LAT, "lon": ORIGIN_LON, "label": os.getenv("OMNIFLEET_THEATRE_NAME", "Demo Test Range · Bengaluru")},
        "width_m": THEATRE_WIDTH_M,
        "coordinate_system": "WGS84 display / local tangent-plane simulation",
        "projection_note": "Illustrative 2 km demo theatre using a local equirectangular approximation; not suitable for real navigation.",
        "bounds": corners,
        "geofence": geofence,
        "no_go_zones": no_go,
        "obstacles": ([{"id":o["id"],"label":o["label"],"moving":False,
                        "polygon":[local_to_wgs84(x,y) for x,y in o["polygon"]]} for o in OBSTACLES]
                      + [{"id":o["id"],"label":o["label"],"moving":True,
                          "polygon":[local_to_wgs84(x,y) for x,y in o["polygon"]]} for o in dynamic_obstacle_state() for o in [{"id":o["id"],"label":o["label"],"polygon":o["polygon"]}]]),
    }


def segment_is_safe(start: tuple[float, float], end: tuple[float, float],
                    clearance: float = 0.0) -> bool:
    """Conservatively sample a segment against the geofence and restricted polygons."""
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    steps = max(1, int(math.ceil(distance / 0.2)))
    for index in range(steps + 1):
        t = index / steps
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        if not in_geofence(x, y):
            return False
        if any(point_in_polygon((x, y), zone) for zone in NO_GO_ZONES):
            return False
        if any(point_in_polygon((x, y), obstacle["polygon"]) for obstacle in OBSTACLES):
            return False
        if any(point_in_polygon((x, y), polygon) for polygon in dynamic_obstacle_polygons()):
            return False
        if clearance:
            for zone in NO_GO_ZONES:
                for px, py in zone:
                    if math.hypot(x-px, y-py) < clearance:
                        return False
    return True

def plan_safe_route(start: tuple[float, float], end: tuple[float, float]) -> list[dict]:
    """Return a short visibility-graph route around restricted polygons.

    Coordinates are local theatre units. This is an illustrative 2-D planner,
    not a validated navigation or obstacle-avoidance system.
    """
    start = (float(start[0]), float(start[1])); end = (float(end[0]), float(end[1]))
    if not in_geofence(*start) or not in_geofence(*end):
        raise ValueError("Route endpoint is outside the operating geofence")
    if in_no_go_zone(*start) or in_no_go_zone(*end):
        raise ValueError("Route endpoint is inside a restricted zone")
    if segment_is_safe(start, end):
        return [{"x": round(end[0], 4), "y": round(end[1], 4)}]

    nodes = [start, end]
    # Add conservative outside-corner nodes for the rectangular demo restrictions.
    route_polygons = list(NO_GO_ZONES) + [o["polygon"] for o in OBSTACLES] + dynamic_obstacle_polygons()
    for zone in route_polygons:
        cx = sum(p[0] for p in zone) / len(zone); cy = sum(p[1] for p in zone) / len(zone)
        for x, y in zone:
            vx, vy = x-cx, y-cy
            scale = 1.0 / max(abs(vx), abs(vy), 1e-9)
            nodes.append((x + vx*scale*1.25, y + vy*scale*1.25))
    edges = {i: [] for i in range(len(nodes))}
    for i in range(len(nodes)):
        for j in range(i+1, len(nodes)):
            if segment_is_safe(nodes[i], nodes[j]):
                d = math.hypot(nodes[i][0]-nodes[j][0], nodes[i][1]-nodes[j][1])
                edges[i].append((j,d)); edges[j].append((i,d))
    import heapq
    queue=[(0.0,0,[0])]; best={0:0.0}; path=None
    while queue:
        cost,node,route=heapq.heappop(queue)
        if node==1: path=route; break
        if cost>best.get(node,float('inf')): continue
        for nxt,weight in edges[node]:
            candidate=cost+weight
            if candidate<best.get(nxt,float('inf')):
                best[nxt]=candidate; heapq.heappush(queue,(candidate,nxt,route+[nxt]))
    if not path:
        raise ValueError("No safe route exists between the selected points")
    return [{"x":round(nodes[i][0],4),"y":round(nodes[i][1],4)} for i in path[1:]]
