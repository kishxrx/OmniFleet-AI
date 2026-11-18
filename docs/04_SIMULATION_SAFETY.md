# Simulation and safety boundary — v0.9.2

- Simulation coordinates use a normalized 0–100 local grid. The map derives illustrative WGS84 display coordinates from a small-area equirectangular approximation; they are not navigation-grade.
- Vehicle speed and acceleration use SI units. Local movement converts metres using the theatre scale (20 m per local unit by default).
- Seeded vehicles start outside the restricted polygon. Safe routing checks complete path segments against the geofence, restricted zone, fixed structure and current moving-obstacle geometry.
- A deterministic moving virtual obstacle travels in a bounded lane. When it blocks a vehicle's proposed step, the simulator attempts a new safe route; if none exists, that vehicle enters a safe hold.
- Pairwise movement uses synchronized closest-approach checks. A deterministic right-of-way rule clips a priority vehicle at the minimum-separation boundary and schedules a lateral detour for the yielding vehicle. If a route cannot be established, the affected vehicle waits and eventually enters `holding`; missions are marked degraded rather than silently completed.
- Minimum vehicle separation is 2 local units (40 m in the default theatre). This is a conservative 2-D demonstration rule, not a validated collision-avoidance controller or aviation separation standard.
- Battery drain is illustrative. Below 20%, the system evaluates return-home route energy with acceleration, a 30% contingency and a protected 5% reserve. If return is infeasible, an aircraft may receive a local emergency-land proposal and a ground robot a safe-hold proposal. The current position must pass safety checks; otherwise recovery is `RECOVERY_UNAVAILABLE`. Operator approval remains mandatory.
- Sensor observations are synthetic geometric footprints. Delayed observations aggregate across retained history; the coordination workflow retries temporary failures up to a bounded number of attempts and never bypasses approval.
- Shared fleet knowledge is recipient-specific and updates only when a heartbeat is delivered. Last-known peer state can become stale while disconnected.
- Peer delivery checks the smaller configured communication radius. Optional latency (0–10 simulation ticks) and deterministic packet loss (0–100%) can be injected. These controls exercise queue/retry behavior; they are not physical RF propagation or stochastic network emulation.
- Coverage planning accepts convex operator-drawn polygons, rejects restricted/obstacle intersections, routes transit to the first lane, and validates generated sweep segments.
- Failure injection and recovery are simulation-only. Recovery proposals are capability-, domain-, availability- and battery-filtered and require operator approval.
- `PX4SITLAdapter` is a non-operational placeholder and refuses dispatch. The application cannot connect to PX4 or physical vehicles.
- Do not use this project for flight testing, navigation, safety-critical decisions or real-world control.
