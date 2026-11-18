# Sensor Intelligence & Blackbox Analytics (v0.9.2)

## Objective
Provide an operator-driven, reproducible test environment for synthetic sensor observation, peer information sharing, observation provenance and post-run telemetry review.

## Sensor model
Each vehicle receives a configurable sensor radius and nominal communication radius. Vehicle-to-object distance is computed in the local 2 km demo theatre. Difficulty scales the sensor radius (`easy=1.0`, `medium=0.82`, `hard=0.64`). Hidden objects, disabled sensors, failed/landed vehicles and vehicles with critically low battery do not create new observations.

When an object is in range, one deterministic observation is recorded per vehicle and object revision. A structured `SENSOR_OBSERVATION` is published through the simulated swarm network. If communication is unavailable, the local observation remains in the ledger with `LOCAL_ONLY` status. In Hybrid mode, peer delivery is blocked when the vehicles are farther apart than the smaller of their configured communication radii. The same symmetric geometric rule is applied to task requests and peer offers.

`CORROBORATED` means at least two distinct simulated vehicles produced observations for the same object revision. It is a count of simulated sources, not proof of identity or a calibrated confidence fusion result. The displayed confidence score is deterministic and should not be interpreted as a probability.

## Sensor-to-coordination automation

After each manual scan and each simulation tick, the retained observation history is grouped by object revision. Delayed corroboration across multiple scans is therefore supported. The default policy requires at least two distinct source vehicles and a per-source confidence of at least `0.65`. The strongest online qualifying observer starts the existing swarm detection/task-offer workflow. If no observer can communicate or no peer can offer, the revision remains retryable with a short tick-based backoff. A revision is marked processed only after a valid pending-approval proposal exists; moving/editing the object increments its revision.

The default policy is configurable and persisted:

- `GET /api/sensors/automation` — read policy.
- `PUT /api/sensors/automation` — update `enabled`, `min_confidence` (0–1) and `min_sources` (1–3).

`POST /api/sensors/scan` returns `automated_proposals` in addition to observations. The UI selects the first new proposal in Mission Control. Every proposal remains `PENDING_APPROVAL`; no automatic dispatch is possible through this path. The automation is deterministic rule-based orchestration, not an AI classifier.

## Interactive objects
Operators can place, move, hide/show and remove virtual objects. Allowed categories are `marker`, `vehicle`, `person`, `structure` and `other`. All coordinates are local 0–100 values and are validated server-side against the operating geofence and no-go polygon. Virtual targets may be placed within the fixed structure footprint for perception experiments, but automated inspection proposals are suppressed when no safe route to the target exists. Object revisions ensure that moving/changing an object permits a fresh synthetic observation. Removed objects disappear from the active map but their blackbox event records and past observations are retained.

## Map overlays
- Sensor rings: per-vehicle configured sensor radius, in metres.
- Comm range: nominal configured communication radius, in metres; this value also constrains direct peer-message reachability using the symmetric geometric rule.
- Test objects: active operator-created objects.
- Observations: synthetic observation locations with source/status popups.

Communication rings are not RF simulations. Direct peer-message delivery uses a symmetric distance gate based on the shorter configured radius. The in-process bus exposes deterministic simulation controls for latency (0–10 ticks) and packet loss (0–100%), but does not model radio power, path loss, terrain, physical obstruction, jamming, encryption, multi-hop routing or real radios. Coordinator-relayed messages do not use the direct-peer distance gate.

## Blackbox
A telemetry sample is written per vehicle on each simulation tick. It includes local position, speed, heading, altitude, battery, status/failure flag, radio state and configured sensor/communication ranges. The UI plots speed and battery, computes distance across the displayed sample window, and supports chronological replay with an explicit map marker. Event records capture operator actions and sensor/object events.

Retention is bounded: up to 1,800 telemetry samples, 800 observations and 600 blackbox events. Snapshot data is stored in SQLite alongside fleet, mission and swarm state.

## Safety and limitations
This module is for benign software testing with virtual markers/objects. It does not ingest camera feeds, perform computer vision, classify threats, identify real people/vehicles, or control hardware. The automated coordination rule consumes synthetic observations only; it is not a perception model. Sensor footprints are isotropic circles rather than directional fields of view. No altitude occlusion, line-of-sight, weather, terrain, optical performance, radio propagation or collision physics is represented. Do not interpret the demo as a real sensor/radio model or use it for navigation or safety-critical decisions.
