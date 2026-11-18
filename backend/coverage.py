from __future__ import annotations
from .geospatial import wgs84_to_local, in_geofence, in_no_go_zone, GEOFENCE, NO_GO_ZONES, point_in_polygon, plan_safe_route, OBSTACLES


def _orientation(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def _segments_intersect(a,b,c,d):
    o1,o2,o3,o4=_orientation(a,b,c),_orientation(a,b,d),_orientation(c,d,a),_orientation(c,d,b)
    return (o1==0 or o2==0 or (o1<0)!=(o2<0)) and (o3==0 or o4==0 or (o3<0)!=(o4<0))

def _polygon_intersects(a,b):
    if any(point_in_polygon(p,b) for p in a) or any(point_in_polygon(p,a) for p in b): return True
    return any(_segments_intersect(a[i],a[(i+1)%len(a)],b[j],b[(j+1)%len(b)]) for i in range(len(a)) for j in range(len(b)))

def _scan_intervals(poly, y):
    xs=[]
    for i,p in enumerate(poly):
        q=poly[(i+1)%len(poly)]
        if (p[1] <= y < q[1]) or (q[1] <= y < p[1]):
            xs.append(p[0]+(y-p[1])*(q[0]-p[0])/(q[1]-p[1]))
    xs.sort()
    return [(xs[i],xs[i+1]) for i in range(0,len(xs)-1,2)]

def _clip_vertical(poly, xmin, xmax):
    out=poly
    for axis,bound,keep_less in ((0,xmax,True),(0,xmin,False)):
        src=out; out=[]
        if not src: break
        for i,p in enumerate(src):
            q=src[(i+1)%len(src)]
            pin=p[axis] <= bound+1e-9 if keep_less else p[axis] >= bound-1e-9
            qin=q[axis] <= bound+1e-9 if keep_less else q[axis] >= bound-1e-9
            if pin and qin: out.append(q)
            elif pin and not qin:
                t=(bound-p[axis])/(q[axis]-p[axis]); out.append((bound,p[1]+t*(q[1]-p[1])))
            elif not pin and qin:
                t=(bound-p[axis])/(q[axis]-p[axis]); out.extend([(bound,p[1]+t*(q[1]-p[1])),q])
    return out

def plan_coverage(polygon_wgs84, fleet, lane_spacing_m=80, max_waypoints=120):
    if len(polygon_wgs84)<3 or len(polygon_wgs84)>40: raise ValueError('Draw an area using 3 to 40 boundary points.')
    poly=[wgs84_to_local(p['latitude'],p['longitude']) for p in polygon_wgs84]
    if len({(round(x,6),round(y,6)) for x,y in poly})<3: raise ValueError('Coverage boundary needs at least three distinct points.')
    if abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly))))<1e-5:
        raise ValueError('Coverage boundary has zero area.')
    # Reject self-intersecting or concave polygons: this version guarantees safe
    # straight-line lane transitions only for simple convex coverage boundaries.
    n=len(poly)
    for i in range(n):
        for j in range(i+1,n):
            if j==i or j==(i+1)%n or i==(j+1)%n: continue
            if _segments_intersect(poly[i],poly[(i+1)%n],poly[j],poly[(j+1)%n]):
                raise ValueError('Coverage boundary must not self-intersect.')
    turns=[_orientation(poly[i],poly[(i+1)%n],poly[(i+2)%n]) for i in range(n)]
    nonzero=[t for t in turns if abs(t)>1e-8]
    if not nonzero or (min(nonzero)<0<max(nonzero)):
        raise ValueError('Use a convex patrol boundary for safe sweep-lane generation.')
    if any(not in_geofence(x,y) for x,y in poly): raise ValueError('Coverage boundary must remain inside the operating geofence.')
    for zone in NO_GO_ZONES:
        if _polygon_intersects(poly,zone): raise ValueError('Coverage area intersects a restricted no-go zone. Redraw the area around it.')
    for obstacle in OBSTACLES:
        if _polygon_intersects(poly,obstacle["polygon"]): raise ValueError(f'Coverage area intersects {obstacle["label"]}. Redraw around the obstacle.')
    available=[v for v in fleet.values() if not v.failed and v.status in ('ready','holding') and 'navigation' in v.capabilities and 'area_coverage' in (v.mission_types or []) and v.battery_pct>=20]
    if not available: raise ValueError('No available vehicles with navigation and area_coverage capability and at least 20% battery.')
    spacing=max(20.0,min(float(lane_spacing_m),300.0))*100.0/2000.0
    minx,maxx=min(p[0] for p in poly),max(p[0] for p in poly)
    miny,maxy=min(p[1] for p in poly),max(p[1] for p in poly)
    # Allocate contiguous vertical strips, preserving deterministic fleet order.
    vehicles=sorted(available,key=lambda v: (v.kind=='ground_robot',v.id))
    # Keep one compatible asset unassigned as a recovery reserve whenever at least 3 coverage-capable assets exist.
    reserve = vehicles[-1] if len(vehicles) >= 3 else None
    if reserve: vehicles = vehicles[:-1]
    bands=[]
    for i,v in enumerate(vehicles):
        left=minx+(maxx-minx)*i/len(vehicles); right=minx+(maxx-minx)*(i+1)/len(vehicles)
        clipped=_clip_vertical(poly,left,right)
        if len(clipped)>=3: bands.append((v,left,right,clipped))
    assignments=[]
    total=0
    for v,left,right,sector in bands:
        sy0=max(miny,min(p[1] for p in sector)); sy1=min(maxy,max(p[1] for p in sector))
        count=max(1,int((sy1-sy0)/spacing)+1)
        ys=[(sy0+sy1)/2] if count==1 else [sy0+(sy1-sy0)*i/(count-1) for i in range(count)]
        points=[]
        for row,y in enumerate(ys):
            intervals=[]
            for a,b in _scan_intervals(poly,y):
                lo,hi=max(a,left),min(b,right)
                if hi-lo>0.5: intervals.append((lo,hi))
            if row%2: intervals.reverse()
            for lo,hi in intervals:
                pair=[(lo,y),(hi,y)] if row%2==0 else [(hi,y),(lo,y)]
                # Conservative sample-based checks on every straight sweep segment.
                for p in pair:
                    if not in_geofence(*p) or in_no_go_zone(*p): raise ValueError('Generated sweep waypoint failed geofence/no-go validation.')
                points.extend(pair)
        if points:
            # Route safely from the vehicle's current position to the first sweep lane.
            route=[]; cursor=(v.x,v.y)
            for point in points:
                leg=plan_safe_route(cursor,point)
                route.extend((float(p['x']),float(p['y'])) for p in leg)
                cursor=point
            total+=len(route)
            if total>max_waypoints: raise ValueError(f'Generated safe route has {total} waypoints; simplify the area or increase lane spacing.')
            assignments.append({'vehicle_id':v.id,'vehicle_name':v.name,'sector':f'SECTOR {len(assignments)+1}',
                'sector_bounds_local':{'west':round(left,3),'east':round(right,3)},
                'action':'coverage','route_points':[{'x':round(x,4),'y':round(y,4)} for x,y in route],
                'x':round(points[0][0],4),'y':round(points[0][1],4),
                'note':'Deterministic lawnmower sweep with safe transit routing; simulated route, operator approval required'})
    if not assignments: raise ValueError('No safe sweep lanes could be generated for this polygon.')
    if total>max_waypoints: raise ValueError(f'Generated route has {total} waypoints; simplify the area or increase lane spacing.')
    # Sector strips are disjoint by construction; report lane and area estimates.
    return {'assignments':assignments,'waypoint_count':total,'lane_spacing_m':round(spacing*20,1),
            'sector_count':len(assignments),'reserve_vehicle':reserve.name if reserve else None,'overlap_check':'PASS — disjoint vertical sector bands',
            'safety_check':'PASS — boundary inside geofence and clear of restricted zones'}
