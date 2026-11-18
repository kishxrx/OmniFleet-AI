# Release Notes

## v0.9.2 documentation refresh — interoperability presentation

- Reframed the README around the interoperability problem OmniFleet explores: a unified operator interface, common asset/capability model, mission orchestration, deterministic policy checks and a shared simulated operating picture.
- Added GitHub-renderable Mermaid architecture diagrams that distinguish the implemented application and simulator path from unimplemented hardware/vendor integration targets.
- Added an explicit implemented / simulated / future status matrix and a staged hardware-integration roadmap.
- Clarified that the adapter boundary is currently method-level, `SimulatedVehicleAdapter` is the only active dispatcher, and `PX4SITLAdapter` refuses dispatch as a placeholder.
- No runtime behavior or hardware integration was added in this documentation refresh.


## v0.9.2 — Safety & Resilience Hardening

- Reworked per-tick vehicle deconfliction: synchronized closest-approach checks, deterministic right-of-way, clipping at the configured separation boundary, lateral peer detours and bounded safe-hold on unresolved blocks.
- Rejected multi-vehicle proposals atomically when any action or final pairwise separation constraint fails.
- Improved collision regression coverage for head-on swaps, crossing trajectories, impossible occupied destinations and safe degradation rather than interpenetration.
- Fixed dynamic-obstacle re-planning bookkeeping and revalidated route segments during movement.
- Clarified the battery recovery fallback: aircraft receive an operator-approved emergency land proposal and ground vehicles an operator-approved safe hold when return-home energy is infeasible; unsafe current locations remain `RECOVERY_UNAVAILABLE`.
- Improved route-energy calculation to include acceleration, contingency and protected landing reserve; approval-time validation repeats the calculation against live simulated state.
- Corrected current documentation for moving virtual obstacles, recipient-specific fleet knowledge, simulated latency, deterministic packet loss and delayed task negotiation.
- Updated the build/API version and the full test report.
- Added the [System Capabilities & Behaviour Specification](SYSTEM_CAPABILITIES_AND_BEHAVIOUR.md), a whole-system reference covering actual v0.9.2 capabilities, component boundaries, decision flows, scenario playbooks, guards, configuration, API mapping, limitations and test traceability. Linked it from the README and documentation index.

## v0.9.1 — Reliable Simulation, Safe Routing & Resilient Coordination

- Corrected movement dimensional consistency: configured speeds and acceleration remain in SI units and local map displacement uses theatre metres-per-unit conversion.
- Moved Scout-2's seeded start position outside the restricted polygon.
- Added sampled segment validation and a deterministic visibility-graph route planner around the restricted zone and a visible fixed virtual structure obstacle.
- Applied safe transit routing to map waypoint, natural-language goto, return-home and area-coverage missions; targets inside obstacle geometry are rejected.
- Added a per-tick 2-D vehicle separation guard with deterministic right-of-way yielding and trajectory-segment conflict scanning.
- Sensor automation now aggregates the retained observation history, supports delayed corroboration, selects an online reporting source, backs off and retries temporary failures, and marks a revision processed only after a valid pending-approval proposal exists.
- Expected radio/coordination failures no longer interrupt simulation tick processing.
- Shared fleet knowledge updates only when heartbeat messages are delivered; disconnected vehicles retain stale last-known state.
- Added low-battery (<20%) return-home proposals. Approval pre-empts the active simulated task and marks it degraded; no automatic dispatch bypasses the operator.
- Area coverage now plans safe transit from the current vehicle position to its first sweep lane and validates static obstacle/restricted geometry.
- Updated dashboard map overlays, API/build version, operator guide, safety limitations and test report.
- Added regression coverage for SI speed, safe initial fleet state, obstacle detours, crossing trajectories, delayed corroboration, retry after radio restoration and low-battery recovery.

## v0.8.0 — Sensor-to-Swarm Automation & Range-Aware Peer Links

- Connected synthetic sensor observations to automatic corroborated-detection orchestration on manual scans and simulation ticks.
- Added configurable automation policy with persisted settings and per-object-revision duplicate suppression.
- Added geometric peer communication-range enforcement.

## v0.7.0 — Sensor Intelligence & Blackbox Analytics

- Interactive virtual object placement, move, visibility and removal.
- Configurable synthetic sensor footprints and nominal communication-range overlays.
- Deterministic sensor scan, observation ledger, source provenance and multi-vehicle corroboration state.
- Structured sensor observation sharing and blackbox telemetry/replay.

## v0.6.0 — Swarm Intelligence & Communications

- Structured peer messages and hybrid/centralized routing simulation.
- Per-vehicle radios, broadcasts, status requests, peer link tests and detection/task-offer negotiation.
- Human approval gate for inspection proposals.

## v0.5.0 — Area Coverage Orchestration

- Operator-drawn convex patrol area, deterministic sweep lanes and sector assignment.
- Reserve-vehicle and simulated recovery proposal support.

## v0.4.0 — Geospatial Operations Layer

- Leaflet/OpenStreetMap display with local schematic fallback.
- WGS84/local theatre conversion, map waypoint tasking, geofence/no-go checks.

## v0.1–v0.3 — Foundation and Enterprise Dashboard

- FastAPI backend, deterministic offline mission planning, safety approval gate, heterogeneous vehicle simulation, SQLite snapshots and dashboard foundation.
