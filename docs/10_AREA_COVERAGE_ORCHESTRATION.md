# Area Coverage Orchestration — v0.5.0

## Objective
Demonstrate coordinated coverage of an operator-drawn geographic patrol area by multiple heterogeneous simulated assets, with deterministic sector assignment, approval gates, route execution and failure reassignment.

## Operator workflow
1. Select **Draw area** in the map's Area Coverage Planner toolbar.
2. Click at least three points to define a patrol boundary; finish the polygon by clicking **Generate sectors**.
3. Choose lane spacing (40–160 m presets; API supports 20–300 m).
4. Review the generated mission: sector count, route waypoint count, spacing, overlap result, safety result and reserve asset.
5. Approve or reject the proposal. No vehicle moves before approval.
6. Approved simulated vehicles follow their ordered sweep waypoint queues.
7. Inject an assigned vehicle failure to mark the mission degraded. The recovery planner can reassign the failed sector to an available reserve asset; the recovery requires a separate approval.

## Planner design
- WGS84 boundary points are converted into the configured local 0–100 theatre coordinate frame.
- This release accepts simple convex polygons only. Concave and self-intersecting shapes are rejected rather than producing ambiguous sweep transitions.
- The polygon must lie inside the operating geofence and must not intersect any restricted no-go polygon.
- The planner divides the polygon's horizontal extent into disjoint vertical sector bands.
- Each sector receives deterministic alternating horizontal sweep lanes (lawnmower pattern).
- When at least three eligible vehicles exist, one vehicle is deliberately left unassigned as a recovery reserve. With fewer than three eligible vehicles, all eligible vehicles may be assigned.
- Lane spacing is configurable and route complexity is capped at 120 generated waypoints across the mission.

## Safety and execution
- The server, not the browser, performs coordinate conversion, polygon validation, geofence checks, no-go checks, vehicle readiness checks and route waypoint/transit checks.
- Coverage missions are created as `PENDING_APPROVAL`.
- Approval repeats safety validation against current fleet state.
- Each vehicle receives one `coverage` action containing an ordered `route_points` array. The simulator advances through this queue one waypoint at a time.
- A vehicle failure clears its local queue, degrades the parent mission and triggers a recovery proposal containing the failed sector route. The parent is marked complete only after the recovery mission completes.

## API
`POST /api/missions/coverage/plan`

Request:
```json
{
  "polygon": [
    {"latitude": 12.97, "longitude": 77.59},
    {"latitude": 12.97, "longitude": 77.60},
    {"latitude": 12.98, "longitude": 77.60},
    {"latitude": 12.98, "longitude": 77.59}
  ],
  "lane_spacing_m": 80
}
```

Response is a mission proposal with `actions`, `coverage_summary`, `coverage_polygon`, `checks`, and `agent_trace`. Use the existing `POST /api/missions/{mission_id}/approve` and `/reject` endpoints to make the operator decision.

## Acceptance checks
- Valid convex boundary generates disjoint sectors.
- One reserve vehicle is retained when three or more assets are available.
- Boundary outside geofence, restricted-zone intersection, concave shape and self-intersection are rejected.
- Route points and sampled transit segments are checked against geofence/no-go constraints.
- Mission does not dispatch before approval.
- Simulator traverses the ordered waypoint queue.
- Failure of an assigned asset creates a recovery proposal for the reserve; recovery approval is required and the parent mission completes after the recovery route.

## Explicit limitations
This is a deterministic software simulation, not an optimal coverage solver, validated flight planner, safety-certified geofence engine or real-time digital twin. The planner detours around the fixed virtual structure and restricted polygon on transit legs. The simulator also maintains a scripted moving-obstacle polygon and can replan when it blocks a proposed movement step, but the vehicle does not sense or predict moving obstacles from perception. The system does not provide validated collision avoidance, terrain clearance, wind, flight-endurance constraints, airspace restrictions, legal permissions, real telemetry, GPS uncertainty, real vehicles or PX4/MAVLink commands. The local equirectangular coordinate approximation and demo geofence are not suitable for real-world navigation.
