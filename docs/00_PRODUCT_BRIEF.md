# Product Brief — OmniFleet AI v0.9.2

OmniFleet AI is a local, software-only demonstration of collaborative, human-supervised orchestration for a heterogeneous simulated fleet. It explores the orchestration side of the interoperability problem: give an operator one text-based mission interface, reason over a common internal asset/capability model, coordinate assignments, validate policy, require approval, and display fleet state in one operating view.

An operator expresses mission intent; the Mission Planner and Fleet Coordinator propose and review actions; deterministic safety policy validates proposals; a human approves; the active `SimulatedVehicleAdapter` dispatches to the local simulator; and the monitor records state and failure events. The project does not implement manufacturer-specific physical vehicle adapters or real telemetry ingestion.

The demo includes map-based waypoint tasking, convex area-coverage planning, simulated vehicle-to-vehicle messaging, synthetic sensor observations on operator-created test objects, shared observation provenance, SQLite persistence and blackbox telemetry/replay.

## Demonstration success criteria

1. Local startup with Python dependencies only; no GPU or external database service.
2. Offline mission planning and offline sensor/swarm/blackbox workflows.
3. Optional server-side Gemini Developer API planning, with offline fallback.
4. Three heterogeneous simulated vehicle profiles.
5. Explicit agent trace, deterministic policy gate and operator approval for dispatch.
6. Human-operated dashboard controls for map, missions, sensor sandbox, swarm and blackbox.
7. Automated backend tests and optional browser interaction acceptance.
8. Clear documentation and explicit simulation/hardware boundaries.

## Implementation boundary

The heterogeneous fleet, motion, sensor observations, radio links and swarm negotiation are simulated. The active dispatch adapter is local-only. `PX4SITLAdapter` is a non-operational placeholder that refuses dispatch. The current dashboard is a shared view of simulator-generated state, not a federated common operating picture sourced from external systems.

## Non-goals

Physical drone/robot control, live manufacturer APIs, real radio networking, MAVLink/MAVSDK/PX4/ROS 2/DDS/MQTT integration, camera processing, computer vision, voice input, certified flight physics, autonomous weapon or engagement functions, production authentication, multi-tenant deployment or safety-critical use.
