# System Capabilities & Behaviour Specification — OmniFleet AI v0.9.2

> **Purpose of this document:** This is the system-level reference for what the current v0.9.2 code actually does, how its components interact, what it accepts or rejects, how it behaves in common and failure scenarios, and where its boundaries are. It describes the shipped implementation, not a future roadmap.
>
> **Operating boundary:** OmniFleet AI is a software-only, 2-D fleet-orchestration simulation. All vehicles, sensors, objects, communications, motion, battery values and telemetry are simulated. Nothing in this document should be interpreted as a real aircraft operating procedure or a claim of flight safety.

## 1. How to read capability statements

The specification uses these labels to avoid confusing a software feature with a real-world capability:

| Label | Meaning |
|---|---|
| **Implemented** | Present in the v0.9.2 source and callable through the application. |
| **Simulated** | Implemented as deterministic or simplified software behaviour, not as a physical model. |
| **Guard / rejection** | The backend refuses a proposed action or blocks a message under a stated condition. |
| **Not implemented** | No current implementation exists; do not assume the system performs it. |
| **Tested** | A corresponding regression or acceptance test exists. This is not proof of formal safety or correctness in all possible states. |

A successful software check means the tested simulation scenario behaved as expected. It does not establish a safety guarantee for physical systems.

## 2. Product objective and operating model

OmniFleet AI demonstrates collaborative, human-supervised orchestration of a small heterogeneous fleet. It turns operator intent or a simulated detection into a structured proposal, checks that proposal against deterministic policies, waits for an explicit operator decision, dispatches approved actions to a local simulator, and records the resulting state and events.

The system demonstrates these capabilities:

- A fleet containing different simulated vehicle types and mission capabilities.
- Natural-language mission proposal generation with an offline fallback and optional Gemini-backed planning.
- Server-side action, capability, coordinate, geofence, obstacle, route and battery checks.
- Operator-drawn area coverage, deterministic sector allocation and sweep-route generation.
- Synthetic sensor observations with source provenance and multi-vehicle corroboration.
- Sensor-triggered task negotiation through a structured in-process swarm message bus.
- Centralized and hybrid peer communication modes, per-vehicle radios, range checks, simulated latency and packet loss.
- Human approval before simulated mission dispatch, including sensor inspection and recovery proposals.
- Simplified movement, geospatial route detours, obstacle response, vehicle separation handling and mission monitoring.
- Failure injection, alternative-vehicle recovery proposals and low-battery recovery proposals.
- SQLite snapshot persistence and per-vehicle Blackbox telemetry/event review.

The operating model is **supervised autonomy**: the system can automatically sense (synthetically), aggregate evidence, negotiate task offers, select candidates, create proposals, monitor execution and recommend recovery. It does not silently dispatch those proposals. The operator remains the authority for mission approval or rejection.

## 3. System architecture and responsibility boundaries

### 3.1 Runtime components

| Component | Responsibility | Decision / execution authority |
|---|---|---|
| Browser dashboard | Operator inputs, map display, mission review, sensor and network controls, Blackbox playback | User-interface layer only; not authoritative for safety checks |
| FastAPI application | HTTP API, lifecycle, orchestration, simulation tick, state persistence | Coordinates the local application |
| Mission Planner | Converts operator text to structured actions | Proposal generation only |
| Fleet Coordinator | Reviews assignment compatibility and orchestrates coordination | Proposal coordination only; cannot override original operator intent in the planner workflow |
| Safety & Policy | Validates allowlists, vehicle state, capabilities, coordinates, geofence, restricted areas, obstacles, route and energy constraints | Can accept or reject; does not dispatch |
| Execution Agent / adapter | Sends approved actions to the selected adapter | Current operational adapter is simulator-only |
| Mission Monitor | Detects completion or degradation and supports recovery proposal creation | Monitoring and proposal generation; no independent dispatch |
| SensorSimulation | Creates synthetic object observations, provenance, telemetry and event history | Simulated sensing and recording only |
| SwarmNetwork | Routes allowlisted messages, keeps recipient-specific heartbeat knowledge, supports offers and acknowledgements | Information transport and deterministic coordination simulation |
| Geospatial layer | Coordinate conversion, geofence and polygon checks, safe route construction | Simplified 2-D geometry |
| Coverage planner | Validates convex patrol polygons and generates sector sweep routes | Deterministic planning proposal only |
| SQLite snapshot store | Saves the current application state | Single-process persistence, not a distributed database |

### 3.2 Architecture diagram

```text
Operator / Browser
       |
       | REST + JSON
       v
FastAPI application -------------------- SQLite snapshot
       |
       +-- Mission Planner (offline / optional Gemini)
       |          |
       |       Fleet Coordinator
       |          |
       |       Safety & Policy ----> reject OR PENDING_APPROVAL
       |                                  |
       |                           Human decision
       |                                  |
       |                           Simulated adapter
       |                                  |
       |                           Mission Monitor
       |
       +-- Coverage planner --------------------+
       |
       +-- SensorSimulation                    |
       |       |                                |
       |       +-- observation history          |
       |       +-- sensor-to-task automation    |
       |                                        |
       +-- SwarmNetwork <-----------------------+
       |       |                                |
       |       +-- TASK_REQUEST / TASK_OFFER    |
       |       +-- HEARTBEAT / ACK              |
       |       +-- latency / packet loss        |
       |
       +-- 2-D vehicle simulator / geospatial checks
       |
       +-- Blackbox telemetry and events
```

This is a **modular monolith**: one FastAPI process owns fleet, mission, sensor, swarm and simulation state. The agents are role-separated application components; this is not a distributed multi-agent runtime with separate autonomous processes per vehicle.

### 3.3 LLM boundary

- Default provider: `offline`; no API key is required.
- Optional provider: `gemini`, configured with `GEMINI_API_KEY` and `GEMINI_MODEL`.
- The Mission Planner and Fleet Coordinator can make separate Gemini requests.
- If the provider is unavailable, returns unusable data, or errors, the application falls back to deterministic offline behaviour.
- In the planner workflow, the coordinator's output is checked against a signature of the original requested actions. If it changes the requested vehicle/action/target intent, the original actions are preserved.
- All resulting actions still pass deterministic backend validation and require operator approval.
- Sensor scans, observation corroboration, swarm negotiation, collision handling, battery estimation and execution are deterministic application logic; they are not LLM decisions.
- No independent LLM is running inside Scout-1, Scout-2 or Relay-1.

## 4. Fleet composition and vehicle model

### 4.1 Seeded assets

The default seed creates three assets. Their values are simulation fixture parameters, not specifications for real hardware.

| Asset | Kind | Start `(x,y)` | Initial altitude | Initial battery | Max speed | Max acceleration | Capabilities | Mission types |
|---|---|---:|---:|---:|---:|---:|---|---|
| Scout-1 | Quadrotor | `(18,25)` | 25 m | 94% | 4 m/s | 2.0 m/s² | navigation, hold, return_home, land | patrol, inspect, area_coverage |
| Scout-2 | Fixed-wing | `(45,60)` | 60 m | 81% | 6 m/s | 1.2 m/s² | navigation, return_home, land | patrol, inspect, area_coverage |
| Relay-1 | Ground robot | `(70,48)` | 0 m | 88% | 2 m/s | 1.0 m/s² | navigation, hold, return_home | patrol, ground_inspection, area_coverage |

All three assets have a default home point of local `(10,10)`. Each vehicle has status, position, altitude, battery, speed, heading, target, route queue, failure flag and a blocked-tick counter.

The listed capability and mission-type labels are application metadata used by deterministic validation and assignment logic. They do not represent validated hardware compatibility. For example, generic `area_coverage` metadata allows the demo planner to allocate a simulated coverage sector; it does not prove that a real ground robot or aircraft can perform an equivalent operation.

### 4.2 Vehicle states

The code uses states including:

| State | Meaning in the simulation |
|---|---|
| `ready` | Available for a new task when other checks also pass |
| `holding` | Stationary / holding; can be eligible for a new task |
| `moving` | Executing a goto or coverage route |
| `returning` | Executing a return-home route |
| `low_battery` | Battery reached the critical stop threshold; movement target and route are cleared |
| `landed` | Simulated aircraft landing action has set altitude to zero and stopped movement |
| `failed` | Failure was injected; vehicle is unavailable |

A vehicle may also have a `failed` boolean independent of its display state. Mission eligibility checks use both availability state and failure state.

### 4.3 Vehicle actions

The execution adapter accepts these action names:

| Action | Effect |
|---|---|
| `goto` | Follow a validated route queue to a local target and finish in `ready` |
| `coverage` | Follow an ordered sweep-route waypoint queue and finish in `ready` |
| `hold` | Clear movement targets and route queue, set speed to zero and enter `holding` |
| `return_home` | Follow a validated route to the vehicle's home point and finish in `ready` |
| `land` | Clear movement, set speed and altitude to zero, enter `landed` |

`coverage` is generated by the coverage endpoint rather than by the basic natural-language action schema. All action types are checked by the safety component before approval and rechecked at approval time.

## 5. Coordinate system, theatre and environment

### 5.1 Local coordinate frame

- Local map coordinates are normalized from `0` to `100` on both axes.
- Default theatre width is 2,000 metres, so the default scale is 20 metres per local coordinate unit.
- The local display converts to/from WGS84 using a small-area equirectangular approximation around a configurable origin.
- Default illustrative origin: latitude `12.9716`, longitude `77.5946` (labelled Bengaluru in the demo).
- Local `x` increases east; local `y` increases north.
- The operating geofence is the square from local `4` to `96` on each axis.

The default origin and boundaries are demo fixtures, not a real operating area. Changing theatre width changes the metres-per-local-unit scale and consequently changes the real-world-equivalent value of local separations and route lengths.

### 5.2 Restricted and obstacle geometry

| Environment feature | Current definition | Behaviour |
|---|---|---|
| Operating geofence | Polygon `(4,4)`, `(96,4)`, `(96,96)`, `(4,96)` | Route endpoints and sampled route segments must remain inside |
| Restricted no-go polygon | `(20,62)`, `(42,62)`, `(42,82)`, `(20,82)` | Waypoints/route segments and coverage boundaries intersecting it are rejected or detoured around where supported |
| Fixed virtual structure | Rectangle from `x=63..72`, `y=66..76` | Destinations inside are rejected; safe route planner seeks a detour |
| Moving virtual obstacle | Scripted rectangle centred initially at `(54,48)`, half-width/height `1.25`, moves horizontally between `x=47..57` at `0.12` local units/s | The simulator updates its deterministic position and can replan/hold when it blocks a movement step |

The moving obstacle is scripted by the simulation. It is not discovered by a perception system. The environment update also prevents the scripted polygon from advancing into a protected vehicle position under its current simple clearance rule.

### 5.3 Route planner

The safe-route planner:

1. Checks that start and end points are within the operating geofence.
2. Rejects endpoints inside the restricted polygon.
3. Checks whether a direct segment is safe.
4. If needed, constructs candidate visibility nodes around the restricted polygon, fixed obstacle and current moving-obstacle polygon.
5. Builds visible safe edges using sampled segment checks.
6. Uses a shortest-path search over the resulting graph to return ordered detour waypoints.
7. Raises a validation error when no safe path is found.

Route-segment checks sample along a segment at approximately 0.2 local-unit intervals. This is a deterministic geometric approximation, not a formal proof that every point on every continuous path is safe.

## 6. Motion, navigation and collision-related behaviour

### 6.1 Motion model

- Speed and acceleration are represented in SI units: metres per second and metres per second squared.
- The theatre scale converts metres travelled into local map displacement.
- A simulation tick normally advances one second; the core tick clamps supplied `dt` to at most two seconds.
- The vehicle accelerates/decelerates toward a desired speed constrained by maximum speed and remaining distance.
- Speed is reset at each route waypoint in the simplified model.
- Heading is updated from the direction of travel.
- Aircraft altitude is a simple state value; during movement it is reduced by a small fixed rate. There is no 3-D flight path planner or altitude-aware collision model.
- Battery drain per simulated second is `0.018 + 0.012 × (achieved_speed / max_speed)` percentage points, with the ratio protected against division by zero.

### 6.2 Vehicle separation guard

The runtime guard uses a configurable local clearance defaulting to 2 local units (40 metres in the default 2 km theatre). For simultaneous proposed movements it:

- Computes the closest approach over the same tick interval rather than comparing only the geometric line segments.
- Applies deterministic priority ordering to resolve a conflict.
- Blocks a yielding vehicle when the priority movement can safely clear the other vehicle's current position.
- Clips a priority movement at the separation boundary in a head-on/close approach case rather than allowing it to step through another vehicle's occupied point.
- Attempts a lateral peer detour when a safe sidestep can be constructed.
- Rechecks proposed movers against vehicles that are stationary for the current tick.
- Permits monotonic movement away from an already-existing overlap so the simulation can recover from a bad initial state instead of trapping both assets.
- If no safe movement is found, the vehicle stops/holds; after repeated blocking (eight blocked ticks in the current core logic) it transitions to `holding` and its movement target is cleared.
- A mission that does not reach its expected terminal vehicle state is degraded rather than falsely marked complete.

This logic is a conservative 2-D heuristic. It is not a 3-D collision-avoidance controller, continuous-time certified controller or aircraft separation standard.

### 6.3 Trajectory conflict scan

The explicit conflict-scan endpoint predicts future positions along each active vehicle's target and queued route. Current parameters are:

- Prediction horizon: 45 seconds.
- Prediction step: 0.25 seconds.
- Clearance threshold: 2 local units.

A conflict is reported when predicted positions approach within the threshold at the same predicted time. Two geometric routes crossing at different times should not be reported solely because their lines intersect. The runtime movement guard still separately checks each tick; the conflict-scan endpoint is an operator-visible prediction, not the sole enforcement mechanism.

### 6.4 Dynamic obstacle handling

A route planned against the current environment may be blocked later as the scripted moving obstacle advances. During movement, the simulator checks the proposed movement segment against the current dynamic obstacle polygon. When blocked, it stops the vehicle and attempts to calculate a new safe route to the existing target. If no route can be found, it enters `holding` and clears the target/route. This is reactive geometric replanning, not sensor-driven moving-object tracking or predictive avoidance.

## 7. Mission planning, validation, approval and execution

### 7.1 Mission proposal flow

```text
Operator instruction / map point / coverage boundary / detection / recovery event
                                      |
                             Structured proposal
                                      |
                         Fleet assignment review
                                      |
                         Deterministic safety checks
                                      |
                    +-----------------+------------------+
                    |                                    |
                  Errors                             All checks pass
                    |                                    |
                REJECTED                            PENDING_APPROVAL
                                                         |
                                            Operator approves or rejects
                                                         |
                                    Approval-time safety revalidation
                                                         |
                                 +-----------------------+----------------+
                                 |                                        |
                              Rejected                              Simulator dispatch
                                                                          |
                                                                  EXECUTING / MONITOR
                                                                          |
                                                           COMPLETED or DEGRADED
```

Mission proposals can originate from:

- Natural-language operator planning (`POST /api/plan`).
- A geographic map waypoint (`POST /api/map/waypoint`).
- An operator-drawn area coverage boundary (`POST /api/missions/coverage/plan`).
- A direct simulated detection and peer-offer exchange (`POST /api/swarm/detections`).
- Sensor-to-swarm automation following corroborated synthetic observations.
- Vehicle-failure or low-battery recovery logic.

### 7.2 Planner behaviour

The offline planner is deliberately small and deterministic. It looks for seeded vehicle names/IDs and direction/task words in the instruction and emits a basic `goto`, `hold`, `return_home` or `land` action. It is not a general natural-language robotics planner. The optional Gemini mode can interpret richer text, but output is treated as untrusted structured input and remains subject to deterministic checks and human review.

### 7.3 Safety validation

The deterministic policy checks, as applicable to an action:

- Action schema and allowlisted action name.
- Vehicle identifier exists.
- Vehicle is available for that type of action, with narrow exceptions for return-home/emergency recovery.
- Vehicle capability/mission-type metadata supports the requested action.
- Coordinates are numeric and inside the normalized 0–100 map and operating geofence.
- Destination is not in the restricted polygon or a currently modelled obstacle.
- A `goto` route can be generated through the current safe-route planner.
- Estimated route energy can preserve the return reserve.
- Coverage route has the expected bounded waypoint list and passes route checks.
- Multi-vehicle proposals satisfy pairwise endpoint/separation constraints.

For multi-vehicle proposals, a failing action or pairwise endpoint constraint rejects the whole proposal atomically; the policy does not return a partially executable action list.

### 7.4 Approval-time revalidation

When an operator selects Approve, the backend:

1. Confirms the mission exists and is `PENDING_APPROVAL`.
2. Requires the simulated operator/coordinator link to be available.
3. Re-runs deterministic safety validation against the current fleet state.
4. Rejects the proposal if current conditions no longer pass.
5. Dispatches the validated actions through `SimulatedVehicleAdapter` only.
6. Announces intent through the simulated swarm layer.
7. Marks the mission `EXECUTING`.

A coordinator outage does not necessarily prevent vehicles from negotiating peer-to-peer in hybrid mode, but the operator cannot approve or reject a mission through the current approval endpoint until the coordinator link is restored.

### 7.5 Mission states and completion

| Mission state | Meaning |
|---|---|
| `PENDING_APPROVAL` | Proposal exists; not dispatched |
| `REJECTED` | Policy validation or operator decision rejected the proposal |
| `EXECUTING` | Approved actions are running in the simulator |
| `COMPLETED` | Every assigned vehicle reached the expected terminal state |
| `DEGRADED` | Failure, low battery, premature stop, unavailable vehicle or other incomplete outcome detected |
| `RECOVERING` | Parent mission is waiting for its linked recovery mission |
| `RECOVERY_UNAVAILABLE` | A recovery proposal could not be safely formed |

The mission monitor does not treat a vehicle that stopped or landed before reaching the expected terminal state as successful completion. A parent mission with an approved recovery can complete after that recovery mission completes.

## 8. Sensor intelligence and observation behaviour

### 8.1 What the sensor model is

SensorSimulation creates synthetic observations by checking the distance between each eligible simulated vehicle and each visible operator-placed virtual object. It does not ingest images or use computer vision.

Default sensor settings and allowed configuration:

| Vehicle kind | Default sensor range | Valid configured range | Default nominal comm range |
|---|---:|---:|---:|
| Quadrotor | 450 m | 50–1,000 m | 1,000 m |
| Fixed-wing | 600 m | 50–1,000 m | 1,200 m |
| Ground robot | 240 m | 50–1,000 m | 650 m |

Nominal communication ranges may be configured from 100 to 2,000 metres. These ranges are independent of the sensor ranges.

### 8.2 Virtual object lifecycle

- Operators may place up to 60 active test objects.
- Allowed categories: `marker`, `vehicle`, `person`, `structure`, `other`.
- Allowed difficulty values: `easy`, `medium`, `hard`.
- Object coordinates must be in the theatre geofence and outside the no-go polygon.
- An object may be set visible or hidden; hidden objects are skipped by scanning.
- Moving/changing an object's position, label, category, difficulty or visibility increments its revision. A new revision may be observed again.
- Deleting an object removes it from the active map but retains prior events and observations in history.
- Objects can be placed in the fixed structure footprint for a sensor demonstration; that does not mean the inspection route to such a point will be accepted. Automated proposals are only created when a safe inspection route validates.

### 8.3 Observation calculation

For each visible object revision and each vehicle:

- Skip if the sensor is disabled, the vehicle failed/landed, or battery is at/below 5%.
- Compute 2-D distance in metres.
- Scale nominal sensor range by difficulty: `easy = 1.0`, `medium = 0.82`, `hard = 0.64`.
- If distance is within effective range, create one deterministic observation per vehicle/object revision.
- Calculate a demo confidence score from proximity and difficulty; the score is bounded from 0.50 to 0.99. It is not a calibrated probability.
- Attach object ID/revision, source vehicle, source name, label/category, local coordinates, distance, confidence, difficulty, timestamp and modality `simulated_sensor_footprint`.
- Attempt to publish the observation as `SENSOR_OBSERVATION` through the swarm network.
- Record whether it was delivered immediately (`SHARED`) or remains local at scan time (`LOCAL_ONLY`).

`CORROBORATED` means at least two distinct simulated source vehicles have observations for the same object revision. It does not establish true object identity or authenticity. Confidence values are not fused into a statistically calibrated score.

### 8.4 Sensor-to-coordination automation

Default policy:

| Setting | Default | Allowed range |
|---|---:|---:|
| Enabled | true | true / false |
| Minimum confidence per source | 0.65 | 0.0–1.0 |
| Minimum distinct sources | 2 | 1–3 |

After a manual scan and each simulation tick, the automation groups the retained observation history by `(object_id, object_revision)`. This allows corroboration to arrive across different scans/ticks. It selects the strongest qualifying observer that is able to communicate and invokes the same simulated detection/task-negotiation flow used by the swarm subsystem.

A revision is marked processed only after a valid pending-approval proposal exists. If coordination cannot be completed because of connectivity/offer conditions, the revision remains eligible for a bounded retry after a short tick-based backoff. Duplicate proposals for the same successfully processed object revision are suppressed. Editing the object creates a new revision and allows new observation/automation.

The automation does **not** dispatch. It creates a proposal for the operator to inspect and approve.

## 9. Swarm communications and coordination

### 9.1 Network modes

| Setting | Behaviour |
|---|---|
| Network enabled | Master switch for simulated message delivery |
| `centralized` mode | Vehicle-to-vehicle traffic relies on the coordinator relay path; coordinator link must be available |
| `hybrid` mode with peer mesh | Direct vehicle-to-vehicle messages are possible without the coordinator, subject to both radios and geometric range |
| Peer mesh enabled | Enables direct peer path in hybrid mode |
| Coordinator link enabled | Enables operator/coordinator message path and the approval/rejection workflow |
| Per-vehicle radio | Sender/receiver radio must be enabled for applicable vehicle messages |

### 9.2 Direct peer range rule

A direct peer message is considered reachable only when:

1. The sender radio is enabled.
2. The receiver radio is enabled.
3. The peer mesh is enabled in hybrid mode.
4. Both positions are known to the network geometry cache.
5. Euclidean separation is no greater than the **smaller** of the sender and receiver configured communication radii.

This is a symmetric geometric reachability rule. It is not RF propagation. No line-of-sight, terrain, antenna, interference, bandwidth or multi-hop path is simulated.

### 9.3 Latency and packet loss controls

| Parameter | Range | Behaviour |
|---|---:|---|
| `network_latency_ticks` | 0–10 | Queues eligible messages for the configured number of simulation ticks before delivery attempt |
| `packet_loss_pct` | 0–100 | Applies deterministic, reproducible per-message/recipient drops |

At delivery time, the network rechecks relevant radio, coordinator-link and direct-peer range conditions. A message queued while a link was valid can therefore be dropped if the required link is no longer valid at delivery time.

These controls are deterministic test fixtures, not a stochastic or RF-accurate network simulator. There is no bandwidth model, routing protocol, congestion model, cryptographic authentication, encryption, QoS or multi-hop mesh routing.

### 9.4 Message protocol

The allowlisted message types are:

`HEARTBEAT`, `POSITION_UPDATE`, `BATTERY_UPDATE`, `AVAILABILITY_UPDATE`, `INTENT_BROADCAST`, `TASK_REQUEST`, `TASK_OFFER`, `DETECTION_EVENT`, `ROUTE_CONFLICT`, `EMERGENCY_ALERT`, `ACKNOWLEDGEMENT`, `STATUS_REQUEST`, `STATUS_REPORT`, `OPERATOR_ANNOUNCEMENT`, `PEER_TEST`, `SENSOR_OBSERVATION`.

Unknown message types and non-object payloads are rejected by the message-bus API.

### 9.5 Heartbeats and fleet knowledge

- Every fifth swarm tick, online vehicles publish heartbeat and associated position, battery and availability updates.
- Heartbeats include status, battery, local position, kind and name.
- A recipient's last-known state is updated only when a heartbeat is delivered to that recipient.
- Coordinator knowledge and each vehicle's recipient-specific knowledge are stored separately.
- If communication is lost, other peers retain stale last-known information; they do not receive omniscient position updates from the simulator's true state.
- Message history is bounded to the most recent 400 messages; the public state exposes a recent window.

### 9.6 Acknowledgements and task negotiation

When a non-acknowledgement message is delivered to a vehicle, an `ACKNOWLEDGEMENT` is published back to the sender. Delayed messages are acknowledged after actual delivery, not merely when queued.

For a simulated detection:

1. Validate source vehicle, source availability, source radio/network and target coordinates.
2. Record and publish a `DETECTION_EVENT`.
3. Identify other available vehicles with inspection mission metadata, at least 20% battery and enabled radios.
4. In hybrid peer mode during coordinator outage, send the task request directly from the source; otherwise use the coordinator-managed route.
5. A compatible recipient returns `TASK_OFFER` with mission type, distance, battery and coordination mode.
6. Offers are collected after any configured delivery delay.
7. Candidates are ordered by estimated local distance; each candidate must pass route/energy safety validation. The first valid candidate is selected.
8. Create a `PENDING_APPROVAL` inspection proposal. No vehicle moves yet.
9. For delayed exchanges, retry coordination at most three attempts. If unsuccessful, the pending exchange expires and sensor automation may retry after its backoff.

The candidate-selection process is deterministic and nearest-valid-candidate oriented. It is not a market-based optimizer, distributed consensus protocol or strategic multi-agent planner.

## 10. Area coverage orchestration

The area-coverage planner accepts WGS84 boundary points and converts them to local simulation coordinates.

Constraints:

- Boundary has 3–40 points and at least three distinct vertices.
- Shape must be non-self-intersecting and convex.
- Polygon must remain inside the operating geofence.
- Polygon must not intersect the no-go zone or fixed simulated structure.
- Lane spacing API range is 20–300 metres (the UI may present a smaller set of presets).
- Total generated route complexity is capped at 120 waypoints.
- Eligible assets must be available (`ready`/`holding`), navigation-capable, marked `area_coverage`, not failed and have at least 20% battery.

Planner behaviour:

1. Sort eligible assets deterministically (aerial profiles before ground robots, then ID).
2. If at least three eligible assets exist, leave one unassigned as a reserve; otherwise all eligible assets may be assigned.
3. Divide the polygon's horizontal extent into disjoint vertical strips.
4. Generate alternating horizontal sweep lanes (lawnmower pattern) within each sector.
5. Connect each vehicle's current position to the sweep lanes using safe transit routes.
6. Reject unsupported/unsafe/over-complex areas rather than emitting an executable invalid proposal.
7. Return a coverage proposal with sector metadata and route waypoints; the operator must approve it.

A failure in an assigned coverage asset can create a separate recovery proposal for another eligible asset. The recovery requires a separate approval. Coverage is a deterministic convex-polygon demo planner, not an optimal search/coverage algorithm and not a real flight planner.

## 11. Battery model and low-energy recovery

### 11.1 Simulated energy model

Battery drain is a simplified percentage-point calculation based on time and achieved speed. The route estimator estimates acceleration and cruise time for each leg, sums the model's base and speed-proportional consumption, multiplies estimated route consumption by a 1.30 contingency, and adds a protected 5% reserve.

Key constants in the current implementation:

| Parameter | Value |
|---|---:|
| Protected reserve | 5 percentage points |
| Planning contingency | 30% |
| Base drain | 0.018 percentage points / second |
| Speed-proportional drain | 0.012 percentage points / second at max speed |
| Low-battery proposal trigger | Below 20% |
| Critical movement stop | At/below 5% |

These values are tuned to this simulator only. They are not calibrated to battery chemistry, payload, temperature, age, wind, hover power, terrain, motor efficiency or real energy consumption.

### 11.2 Recovery decision

When a non-failed, non-landed vehicle drops below 20%:

1. Check whether a pending or executing recovery proposal already exists for that vehicle.
2. Generate a safe route to the configured home point and estimate energy.
3. If the route can preserve the 5% reserve plus modeled contingency, create an operator-approved `return_home` proposal.
4. If return-home is infeasible, try an emergency local recovery action: `land` for a vehicle with landing capability (aircraft) or `hold` for a ground robot.
5. The current location must pass the relevant safety validation; otherwise status is `RECOVERY_UNAVAILABLE`.
6. Operator approval is still required.

An approved return-home recovery can pre-empt another executing mission for that vehicle; the previous mission is marked degraded. At/below 5%, normal sensor scans skip the vehicle and the movement simulation sets the vehicle to `low_battery`, clears its active target/route and stops movement. The recovery proposal path is designed to offer an emergency action rather than silently dispatch it.

## 12. Failure detection and recovery proposals

The `/api/vehicles/{vehicle_id}/fail` endpoint injects a simulated failure:

- Marks the selected vehicle failed and clears its target/route/speed.
- Publishes an `EMERGENCY_ALERT` when the network allows it.
- Marks any executing mission assigned to that vehicle `DEGRADED`.
- For incomplete `goto` or `coverage` tasks, searches for an alternate eligible asset.
- Candidate must be non-failed, `ready`/`holding`, navigation-capable, meet required mission-type metadata and have at least 20% battery.
- For non-coverage tasks, candidate must match the failed vehicle's air/ground domain. Coverage reassignment uses the generic area-coverage mission type and may use another coverage-capable kind.
- Candidates are ordered by distance from the failed vehicle.
- A separate recovery mission is created as `PENDING_APPROVAL` when an eligible candidate can be proposed; otherwise it is `RECOVERY_UNAVAILABLE`.
- A parent mission is linked to the recovery and can complete after the recovery mission completes.

This is deterministic failure injection and reassignment. It does not discover hardware faults, diagnose a component, estimate a real failure probability or autonomously dispatch a replacement.

## 13. Blackbox, telemetry and persistence

### 13.1 Telemetry per simulation tick

One sample per vehicle is captured each simulation tick. Fields include:

- Sample ID and tick number.
- Timestamp, vehicle ID and vehicle name.
- Local `x` and `y`, speed, heading and altitude.
- Battery, status and failure flag.
- Radio enabled state.
- Sensor enabled state and configured sensor/communication ranges.

The dashboard can filter by vehicle, plot speed/battery, replay stored samples chronologically and mark the selected sample on the map. The displayed data are simulator state, not real telemetry.

### 13.2 Event history and retention bounds

Sensor/Blackbox retention limits:

| Record | Maximum retained |
|---|---:|
| Active virtual test objects | 60 |
| Observations | 800 |
| Telemetry samples | 1,800 |
| Blackbox sensor events | 600 |

The application-level event stream separately retains a bounded recent history. Object deletion removes an object from active state but preserves relevant prior event and observation history within retention limits.

### 13.3 SQLite snapshots

The application writes a single local SQLite snapshot containing fleet state, missions, recent application events, swarm state and sensor/Blackbox state. The default path is `data/omnifleet.sqlite3`, overridable through `OMNIFLEET_DB`. On startup, an existing snapshot is restored; otherwise the demo fleet is seeded. `/api/fleet/seed` resets the demo simulation and its histories.

This persistence model is for a single-process local demo. It is not a multi-user transactional event store, distributed state system or production backup strategy.

## 14. Operator-facing features

| Dashboard area | What the operator can do |
|---|---|
| Mission Control | Enter instruction, generate plan, inspect actions/checks/agent trace, approve or reject a pending proposal |
| Operational map | Inspect fleet positions, targets, routes, geofence/no-go areas, obstacle and sensor/network/object/observation overlays; create a map waypoint proposal |
| Area Coverage | Draw and clear a polygon, set lane spacing, generate sector proposals, approve or reject |
| Fleet Assets / resilience | Inspect vehicle state and inject a simulated vehicle failure to test recovery proposals |
| Sensor Intelligence | Place, move, hide/show and delete virtual objects; scan; enable/disable vehicle sensors; adjust sensor and comm ranges; configure automation thresholds |
| Blackbox Analytics | Select vehicle, inspect telemetry/events, play/pause/scrub replay and show replay position on the map |
| Swarm Intelligence & Communications | Pause/resume network, choose centralized/hybrid mode, toggle peer/coordinator links and vehicle radios, configure latency/loss, broadcast, request status, test peer links, simulate detections and scan route conflicts |
| Global controls | Refresh state, reset the simulation after confirmation, open operator help |

Some dashboard elements are informational or roadmap placeholders. See [Control Wiring & QA Matrix](CONTROL_WIRING.md) for the exact actionable-versus-display-only inventory.

## 15. Scenario playbook

Each scenario describes current v0.9.2 behaviour. “Expected” is the intended result for the stated conditions, not a guarantee outside those conditions.

### Scenario A — A normal operator waypoint mission

1. Operator selects a vehicle and geographic target.
2. Backend converts WGS84 to the local theatre frame.
3. Backend checks geofence, no-go and destination/route geometry, vehicle readiness/capability and route energy.
4. A mission proposal is stored as `PENDING_APPROVAL`.
5. Operator reviews the target and checks, then approves.
6. Backend revalidates against current state and dispatches to the simulated adapter.
7. Vehicle follows its route queue, including generated detour points where needed.
8. Mission monitor marks it `COMPLETED` only when the vehicle reaches the expected state; otherwise it may become `DEGRADED`.

**Rejects / prevents in this path:** invalid vehicle ID, unavailable asset, unsupported navigation, out-of-bounds/geofence target, no-go/obstacle endpoint, no safe route, insufficient estimated battery, and approval if coordinator link is unavailable. It does not establish a real-world safe route.

### Scenario B — Two vehicles observe the same object on separate scans

1. Operator places a visible virtual object in the theatre.
2. Scout-1 enters the effective sensor circle and produces a local observation.
3. Scout-2 may observe it on a later scan/tick; the earlier record is retained.
4. Automation groups the full history by object ID and revision.
5. If the configured number of distinct sources each meet the confidence threshold, the system selects a qualifying observer able to communicate.
6. The observer emits a detection event and requests peer inspection offers.
7. The nearest safe eligible offer is selected and turned into a pending mission proposal.
8. The operator reviews and approves; only then does the selected inspector move.

**Key distinction:** `CORROBORATED` is synthetic multi-source corroboration, not proof of an object's identity. If no offer or safe route exists, no executable proposal is created; the automation remains retryable after its configured tick-based backoff.

### Scenario C — A vehicle detects an object but its radio is off

1. Local geometric sensing may still create the observation.
2. Publication from the radio-disabled source is blocked by the network layer.
3. The observation remains visible as local-only in the ledger.
4. That source cannot successfully start a coordination exchange through the network.
5. Once a suitable observer has an active link, later automation attempts can retry the object revision if no valid proposal was previously created.

The network does not invent a link or silently share the observation through an unavailable radio.

### Scenario D — Coordinator offline, hybrid peer mesh online

1. Operator enables hybrid mode and peer mesh.
2. Coordinator link is switched off; the individual vehicle radios and peer range still apply.
3. An online source can deliver a task request directly to reachable peers.
4. A reachable candidate may return a task offer; the inspection proposal can be created while the coordinator is unavailable.
5. The proposal remains pending approval.
6. The operator must restore the coordinator link before the approve/reject endpoint accepts the decision.

This demonstrates separation between peer task negotiation and operator approval authority.

### Scenario E — Centralized mode with coordinator outage

1. Operator selects centralized mode.
2. Inter-vehicle traffic requires the coordinator relay path.
3. If the coordinator link is down, the relay route is unavailable.
4. Peer offers are not delivered through a direct mesh bypass because peer mesh is not the selected mode.
5. The system records blocked/failed delivery and bounded coordination retries apply where the delayed negotiation workflow is active.

### Scenario F — Message latency, packet loss or moving out of range

1. Operator sets latency to 0–10 ticks and packet loss to 0–100%.
2. Eligible messages may be queued or deterministically dropped.
3. At delivery, the network rechecks current radio/link and peer-range conditions.
4. If the required link has disappeared, the queued recipient is marked dropped rather than delivered.
5. A delivered vehicle message receives an acknowledgement; a queued-but-not-yet-delivered message is not acknowledged prematurely.
6. Task negotiation retries are bounded to three attempts; after expiry the pending exchange is cleared and eligible sensor automation can retry after a short backoff.

### Scenario G — A waypoint crosses a no-go zone or obstacle

1. Operator chooses a destination outside restricted geometry.
2. Destination validation passes only if the point itself is inside the geofence and outside no-go/obstacle polygons.
3. Planner checks the entire route segment using sampled geometry.
4. If the direct line is blocked but a visibility-graph detour exists, the route contains extra waypoints around the restriction.
5. If no valid path exists, proposal generation or approval-time revalidation rejects it.
6. If a moving obstacle later blocks the current movement segment, the simulator stops and attempts runtime replanning; if none is found, it enters safe hold and the mission does not falsely complete.

A map waypoint inside a prohibited area is rejected; it is not automatically moved to another destination.

### Scenario H — Two vehicles approach a crossing or head-on path

1. Each vehicle has an approved route and a per-tick movement proposal is computed.
2. The runtime guard calculates synchronized closest approach.
3. Deterministic right-of-way chooses a movement to yield where possible.
4. A vehicle may be clipped at the clearance boundary while the other is held or assigned a lateral detour.
5. If no safe detour is found, one or both vehicles stop/hold; repeated blocking clears the route and the mission is marked degraded.
6. The separate conflict-scan endpoint can report predicted closest approach over its 45-second horizon.

This is a local 2-D heuristic. It does not guarantee collision-free behaviour for arbitrary numbers of vehicles, 3-D motion or every possible initial state.

### Scenario I — Battery drops below 20%

1. Tick processing checks each non-failed, non-landed vehicle below 20%.
2. If no active recovery proposal exists, the system plans a safe return-home route.
3. Energy estimation includes acceleration/cruise time, 30% contingency and 5% reserve.
4. If feasible, create a `PENDING_APPROVAL` return-home proposal.
5. If infeasible, try emergency `land` for an aircraft or `hold` for a ground robot, provided local safety validation passes.
6. If neither route nor local recovery is valid, emit `RECOVERY_UNAVAILABLE`.
7. The operator must approve; an approved return can pre-empt an executing task and mark that prior task degraded.

At/below 5%, movement stops and normal sensor scans skip the vehicle. This threshold is a simulator rule, not a real battery safety threshold.

### Scenario J — A vehicle fails during a mission

1. Operator/test harness injects failure through the failure endpoint.
2. Vehicle becomes failed and is stopped.
3. Any executing mission using it is marked degraded.
4. Recovery logic searches for a compatible ready/holding alternative with adequate battery.
5. A recovery proposal is created for review, or marked unavailable if no suitable alternative exists.
6. The operator separately approves the recovery.
7. If the recovery mission completes, the linked parent mission may be marked complete.

This is failure injection and deterministic reassignment, not autonomous fault diagnosis or hardware failover.

### Scenario K — Multi-vehicle area coverage

1. Operator draws a WGS84 polygon with 3–40 points.
2. Server converts it to local coordinates and rejects self-intersection, concavity, zero area, out-of-geofence boundary, no-go intersection and fixed-structure intersection.
3. Available coverage-capable assets with at least 20% battery are sorted deterministically.
4. With at least three eligible assets, one is kept as an unassigned reserve.
5. Area is divided into disjoint vertical bands; alternating horizontal sweep lanes are generated.
6. Safe transit paths connect each asset to its first lane.
7. Proposal is rejected if route complexity exceeds 120 waypoints.
8. Coverage proposal is presented for human approval and vehicles execute their queued sweep routes only after approval.
9. If an assigned vehicle fails, a separate coverage recovery proposal can be generated for an eligible reserve.

### Scenario L — Mission cannot complete as planned

If a vehicle fails, enters `low_battery`, is stopped by a persistent conflict, loses its expected terminal state or otherwise cannot complete its assigned action, Mission Monitor marks the mission `DEGRADED`. A vehicle merely stopping or being forced into a hold is not considered successful completion of a goto/coverage/return action.

## 16. API capability map

The complete request/response schema and examples are maintained in [API Reference](API_REFERENCE.md). This table maps endpoint groups to their system purpose.

| Method | Endpoint | Capability |
|---|---|---|
| `GET` | `/api/health` | Health, release and active adapter identity |
| `GET` | `/api/state` | Fleet, missions, events, summary and environment state |
| `GET` | `/api/events` | Recent event stream |
| `GET` | `/api/map/config` | Theatre bounds, coordinate origin, geofence, no-go and obstacle polygons |
| `POST` | `/api/map/waypoint` | Create a human-approved map waypoint proposal |
| `POST` | `/api/missions/coverage/plan` | Create area-coverage proposal |
| `POST` | `/api/plan` | Natural-language mission proposal |
| `POST` | `/api/missions/{id}/approve` | Approval-time validation and simulator dispatch |
| `POST` | `/api/missions/{id}/reject` | Reject pending proposal |
| `POST` | `/api/vehicles/{id}/fail` | Inject simulated failure and create recovery proposal(s) |
| `POST` | `/api/fleet/seed` | Reset seeded fleet and simulation histories |
| `POST` | `/api/simulation/tick` | Advance environment, movement, network, sensors, recovery and monitor |
| `GET` | `/api/sensors/state` | Object, settings, observations and overlap state |
| `POST` | `/api/sensors/objects` | Create a virtual object |
| `PUT` | `/api/sensors/objects/{id}` | Update object and increment revision when changed |
| `DELETE` | `/api/sensors/objects/{id}` | Remove active virtual object |
| `PUT` | `/api/sensors/vehicles/{id}` | Configure sensor and comm range settings |
| `POST` | `/api/sensors/scan` | Scan and evaluate sensor automation |
| `GET` / `PUT` | `/api/sensors/automation` | Read/update corroboration policy |
| `GET` | `/api/blackbox` | Telemetry samples and event history |
| `GET` | `/api/blackbox/events` | Filtered Blackbox events |
| `GET` | `/api/swarm/state` | Network config, messages, pending delivery and knowledge |
| `PUT` | `/api/swarm/config` | Network mode, links, latency and packet loss |
| `PUT` | `/api/swarm/vehicles/{id}/radio` | Toggle vehicle radio |
| `POST` | `/api/swarm/broadcast` | Send informational message |
| `POST` | `/api/swarm/status-request` | Request status from reachable vehicles |
| `POST` | `/api/swarm/peer-test` | Test a simulated peer link |
| `POST` | `/api/swarm/detections` | Submit a simulated detection and initiate task negotiation |
| `POST` | `/api/swarm/conflicts/check` | Predict synchronized route conflicts |

## 17. Configuration reference

### 17.1 Environment variables

| Variable | Default | Effect |
|---|---|---|
| `AI_PROVIDER` | `offline` | Selects deterministic offline planning or optional `gemini` provider |
| `GEMINI_API_KEY` | empty | Optional server-side Gemini Developer API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier |
| `OMNIFLEET_DB` | `data/omnifleet.sqlite3` | SQLite snapshot path |
| `OMNIFLEET_THEATRE_NAME` | `Demo Test Range - Bengaluru` | Display label for illustrative theatre |
| `OMNIFLEET_ORIGIN_LAT` | `12.9716` | Illustrative theatre origin latitude |
| `OMNIFLEET_ORIGIN_LON` | `77.5946` | Illustrative theatre origin longitude |
| `OMNIFLEET_THEATRE_WIDTH_M` | `2000` | Physical-equivalent width of local 0–100 simulation grid |

### 17.2 Runtime controls

| Control | Default | Range / values | Effect |
|---|---:|---|---|
| Coordination mode | `hybrid` | `centralized`, `hybrid` | Select coordinator relay or peer mesh option |
| Swarm enabled | true | boolean | Master message-bus switch |
| Peer mesh enabled | true | boolean | Enables direct peer path in hybrid mode |
| Coordinator link | true | boolean | Enables coordinator/operator communication and approval workflow |
| Vehicle radio | true per seeded vehicle | boolean | Enables/suppresses radio messages per vehicle |
| Network latency | 0 ticks | 0–10 ticks | Delivery delay |
| Packet loss | 0% | 0–100% | Deterministic recipient-level loss |
| Sensor automation | true | boolean | Enables automatic detection coordination |
| Minimum confidence | 0.65 | 0–1 | Per-source confidence threshold |
| Minimum sources | 2 | 1–3 | Distinct source vehicle threshold |
| Sensor enabled | true per vehicle | boolean | Allows/skips synthetic scan for that vehicle |
| Sensor range | vehicle-kind default | 50–1,000 m | Synthetic observation radius before difficulty scaling |
| Communication range | vehicle-kind default | 100–2,000 m | Nominal radius used by direct peer geometry gate |
| Coverage lane spacing | 80 m default | API 20–300 m | Separation between sweep rows |

### 17.3 Reset semantics

`POST /api/fleet/seed` recreates the default fleet, clears mission and event history, resets the scripted moving obstacle, reinitializes swarm and sensor systems, and captures a fresh initial telemetry sample. It is a destructive demo reset; save any state you need before using it.

## 18. What the system prevents, rejects or constrains

The following are implemented backend guards, subject to their stated simulation assumptions:

| Condition | Current response |
|---|---|
| Unknown vehicle ID | Reject request/proposal |
| Unsupported action | Reject proposal |
| Vehicle unavailable / failed | Reject new ordinary task |
| Capability or mission-type mismatch | Reject assignment |
| More than 10 actions in a natural-language mission proposal | Reject proposal |
| Coordinate outside local map/geofence | Reject |
| Destination inside no-go or modelled obstacle | Reject |
| Route crosses sampled restricted geometry and safe detour exists | Replace direct segment with detour route |
| No safe route available | Reject/hold rather than dispatch invalid route |
| Insufficient modeled route energy | Reject goto/return-home or choose emergency local recovery proposal |
| Multi-vehicle proposal violates endpoint separation | Reject the whole proposal atomically |
| Coordinator link down during approve/reject | HTTP 409; proposal is not dispatched/rejected through that endpoint |
| Radio/network disabled or peer out of range | Block/drop relevant simulated message |
| Unsupported swarm message type | Reject message |
| Hidden object or disabled/failed/landed/critically low-battery sensor source | Skip new observation |
| Invalid/concave/self-intersecting coverage boundary | Reject coverage proposal |
| Persistently blocked vehicle route | Stop/hold; mission is degraded rather than marked complete |
| No eligible recovery candidate | Mark recovery unavailable; do not invent an alternate |

These are software controls. They do not constitute a safety case, legal geofence, flight termination system, certified separation assurance or protection against all states and bugs.

## 19. Explicit non-capabilities and limitations

The following are **not implemented** in v0.9.2:

- Physical drone, ground robot, camera, GNSS, sensor or radio connectivity.
- PX4, MAVLink, MAVSDK, ROS 2, DDS or MQTT transport. The PX4 adapter is a placeholder that raises an error and sends no commands.
- Camera frame ingestion, computer vision, image segmentation, object detection/classification, target identity confirmation or visual tracking.
- True sensor characteristics: field-of-view, occlusion, line-of-sight, optical performance, noise, uncertainty calibration or altitude-dependent footprint.
- Real RF modelling: propagation, terrain/antenna effects, interference, bandwidth, congestion, jamming, authentication, encryption, QoS or multi-hop mesh routing.
- Independent vehicle-local AI agents, distributed consensus, strategic multi-objective task allocation or adaptive learning.
- Validated 3-D flight/ground physics, wind/weather, terrain, aerodynamic/rotor dynamics, payload effects, realistic inertia or vertical collision avoidance.
- Formally verified collision avoidance, safety-certified separation, airspace authorization or navigation-grade route guarantees.
- Real battery chemistry, battery health, endurance prediction or hardware-specific emergency landing performance.
- Real fault detection, diagnosis, redundancy management or physical vehicle failover.
- Multi-user authentication/authorization, production security controls, hardened audit integrity, production scaling or multi-process coordination.

Additional current limitations:

- The local equirectangular map projection is an approximation for a small illustrative theatre.
- Route checks use finite spatial sampling and small-area polygons.
- Collision/separation checks are simplified 2-D heuristics using one configurable local clearance.
- Moving obstacle behaviour is scripted rather than perceived.
- Coverage supports simple convex polygons only and uses deterministic band allocation rather than a globally optimal planner.
- LLM availability and semantic quality are not guaranteed; deterministic validation and approval remain mandatory.

## 20. Security and operating restrictions

- The local demo has no login, role-based authorization, CSRF protection, rate limiting or hardened production secrets-management layer.
- Keep it on localhost or another trusted development environment. Do not expose it directly to an untrusted/public network.
- Keep `.env` out of version control; do not commit or share API keys.
- Do not use the software for physical navigation, surveillance, airspace decisions, flight tests, real-world emergency decisions or safety-critical operations.
- Any hardware-oriented successor needs a separate system architecture, threat model, hazard analysis, formal requirements, qualified control/perception stack, secure communication design, hardware-in-the-loop validation, regulatory review and qualified human oversight.

## 21. Implementation and verification traceability

The following code files are the primary implementation references. The tests named below are the regression references in this release.

| Capability | Implementation | Representative tests |
|---|---|---|
| Seed fleet, movement, separation, obstacle response | `backend/core.py` | `tests/test_core.py`: `test_heterogeneous_fleet`, `test_sim_speed_uses_metres_per_second_not_local_grid_units`, `test_vehicle_separation_guard_prevents_head_on_swap_collision`, `test_perpendicular_crossing_routes_detour_without_breaching_separation`, `test_moving_obstacle_avoidance_completes_route_without_entering_obstacle` |
| Geofence, coordinate conversion and safe paths | `backend/geospatial.py` | `tests/test_core.py`: `test_wgs84_local_round_trip_and_geofence`, `test_route_planner_detours_around_simulated_structure_obstacle`, `test_route_planner_detours_around_moving_obstacle_and_map_exposes_it` |
| Mission planning, policy, battery and monitor | `backend/agents.py` | `tests/test_core.py`: `test_offline_multi_vehicle_proposal`, `test_coordinator_cannot_rewrite_planner_intent`, `test_return_home_validation_rejects_insufficient_energy`, `test_mission_monitor_does_not_mark_premature_landing_as_completed` |
| Sensor objects, scanning, corroboration and Blackbox | `backend/sensors.py` | `tests/test_sensors.py`: `test_virtual_object_detected_by_two_vehicles_and_shared_over_swarm`, `test_delayed_observation_corroboration_uses_full_history`, `test_sensor_scan_automatically_creates_inspection_proposal_but_never_dispatches`, `test_blackbox_telemetry_events_and_replay_data` |
| Swarm routing, latency, loss and recipient knowledge | `backend/swarm.py` | `tests/test_swarm.py`: `test_hybrid_peer_mesh_operates_during_coordinator_link_loss`, `test_peer_mesh_enforces_configured_radio_range`, `test_recipient_specific_vehicle_knowledge_is_not_globally_shared`, `test_network_latency_queues_then_delivers_after_configured_ticks`, `test_packet_loss_is_deterministically_applied` |
| HTTP orchestration, approval, failure and tick lifecycle | `backend/main.py` | `tests/test_acceptance_api.py` and end-to-end tests in `tests/test_core.py`, `tests/test_sensors.py`, `tests/test_swarm.py` |
| Area coverage | `backend/coverage.py` | `tests/test_core.py`: `test_coverage_planner_splits_disjoint_sectors_and_keeps_reserve`, `test_coverage_planner_rejects_concave_boundary_for_safe_sweep`, `test_coverage_mission_end_to_end_and_reserve_recovery` |
| Simulator-only dispatch boundary | `backend/adapters.py` | `tests/test_core.py`: `test_px4_placeholder_never_sends_commands` |

For reproducible full-suite and browser verification instructions/results, see [Testing & Verification](TESTING_AND_VERIFICATION.md) and [Acceptance Test Matrix](07_ACCEPTANCE_TESTS.md). Tests cover selected deterministic cases; they do not prove every state space or establish real-world safety.

## 22. Related documentation

- [README](../README.md) — project entry point and quick-start.
- [Documentation Index](INDEX.md) — full documentation map.
- [System Architecture](01_SYSTEM_ARCHITECTURE.md) — architecture and main data flows.
- [Agent Design](02_AGENT_DESIGN.md) — agent roles and LLM boundaries.
- [Operator Guide](OPERATOR_GUIDE.md) — dashboard procedures and operator scenarios.
- [API Reference](API_REFERENCE.md) — endpoint contracts and payload examples.
- [Swarm Communications](11_SWARM_COMMUNICATIONS.md) — network/message details.
- [Sensor Intelligence & Blackbox](13_SENSOR_INTELLIGENCE_BLACKBOX.md) — observation and telemetry details.
- [Geospatial Operations Layer](09_GEOSPATIAL_OPERATIONS_LAYER.md) — coordinate and route details.
- [Area Coverage Orchestration](10_AREA_COVERAGE_ORCHESTRATION.md) — sector and sweep planning.
- [Safety & Limitations](SAFETY_AND_LIMITATIONS.md) — operational and security restrictions.
- [Testing & Verification](TESTING_AND_VERIFICATION.md) — reproducible test scope and results.

---

**Specification status:** Descriptive system reference for the v0.9.2 codebase. Update this document when implemented behaviour, configuration defaults, API contracts or limitations change. Do not use it as a flight manual or safety assurance document.
