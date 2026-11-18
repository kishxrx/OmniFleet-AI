# Interoperability Scope and Integration Roadmap — v0.9.2

## Purpose

OmniFleet explores an important systems problem: how can an operator express a mission once while an orchestration layer coordinates autonomous assets with different identities, capabilities and operating constraints?

A practical interoperability platform needs at least two complementary sides:

- **Orchestration:** understand intent, select compatible assets, validate policy, coordinate tasks and present a shared operating picture.
- **Platform integration:** communicate with each manufacturer's systems, translate commands, normalize telemetry and handle protocol-specific failure modes.

OmniFleet v0.9.2 demonstrates selected orchestration workflows against simulated assets. It does not implement the platform-integration side for physical products.

## Implementation status

| Area | Status in v0.9.2 | What that means |
|---|---|---|
| Natural-language mission input | Implemented | Text instructions are parsed by a deterministic offline planner or optional Gemini-backed Planner. This is not voice input. |
| Fleet identity and capability checks | Implemented in simulation | The backend checks known vehicle IDs, availability, supported actions and mission capabilities against seeded simulated profiles. |
| Heterogeneous fleet | Simulated | The demo contains two aerial profiles and one ground-robot profile with different kinds/capability metadata. They are not connected to real manufacturers. |
| Fleet coordination | Implemented in simulation | A coordinator reviews assignments; deterministic policy checks compatibility before approval. |
| Human approval | Implemented | Proposals remain pending until operator approval; backend validation is repeated before dispatch. |
| Mission execution | Implemented in simulation | Approved actions are dispatched to local simulator objects through `SimulatedVehicleAdapter`. |
| Shared operating picture | Implemented from simulated state | The dashboard combines fleet state, mission status, synthetic sensor observations, swarm messages and blackbox data. |
| Swarm communication | Simulated | An in-process message bus models links, latency, packet loss and negotiation. No radio or network transport is used. |
| Sensor information sharing | Simulated | Observations are generated from virtual objects and geometric sensor footprints. No physical camera or computer vision pipeline exists. |
| Route and separation guards | Simulated | Deterministic 2-D simulator checks and heuristics are exercised; they are not certified or validated flight-control safeguards. |
| Persistent state | Implemented locally | SQLite stores application snapshots for this single-process demo. |
| Manufacturer-specific API adapters | Not implemented | No live vendor API, SDK or command protocol is connected. |
| PX4 / MAVLink / MAVSDK | Placeholder only | `PX4SITLAdapter` explicitly refuses dispatch and is not wired into the application. |
| ROS 2 / DDS / MQTT integration | Not implemented | No robotics middleware or broker connection is created. |
| Real vehicle telemetry | Not implemented | All displayed vehicle state is simulator-generated. |
| Physical sensor / camera / computer vision | Not implemented | No real sensor data or visual inference is ingested. |
| Voice / speech interface | Not implemented | The operator interface accepts text. |
| External command-and-control federation | Not implemented | There is no connection to an external C2 platform or operational common operating picture. |
| Production security and multi-user deployment | Not implemented | The local demo has no production authentication, authorization, transport security or multi-tenant controls. |

## What the project demonstrates

The strongest demonstrated engineering contribution is the separation of operator intent, proposal generation, deterministic policy validation, human approval and execution. That separation is useful when designing an orchestration layer for mixed autonomous systems because it creates a controlled point where asset identity, capability and mission constraints can be checked before a command is sent.

The simulator also makes several coordination workflows observable and testable: multi-vehicle assignment, incompatible replacement rejection, simulated failure recovery, area-coverage allocation, swarm-message negotiation, synthetic observation sharing and blackbox replay.

These are meaningful software architecture and simulation demonstrations. They should not be described as field-tested robotics, physical fleet interoperability or real-world autonomous operation.

## What would be required to extend it

A future integration programme should proceed in controlled stages:

1. **Specify a stable adapter contract.** Define asset discovery, supported capabilities, command schema, command lifecycle, acknowledgements, telemetry, health and fault models.
2. **Build one non-operational integration test adapter.** Exercise serialization, timeouts, retries, idempotency, cancellation and error mapping against a mock vendor endpoint before connecting hardware.
3. **Integrate one platform in a software-in-the-loop environment.** Add vendor-specific translation and verify state reconciliation and failure handling without physical actuation.
4. **Add telemetry normalization.** Preserve source identity, timestamps, coordinate frames, units, quality/freshness and vendor-specific metadata.
5. **Harden the trust boundary.** Add identity, scoped authorization, authenticated/encrypted communications, audit controls, deployment isolation and operator override procedures.
6. **Validate independently before physical use.** Conduct hazard analysis, hardware-in-the-loop testing, integration testing and regulatory/safety review with qualified specialists.

This roadmap is prospective. No stage beyond the current local simulator should be implied as complete.

## Safe portfolio description

> OmniFleet AI is a simulation-first project exploring heterogeneous fleet mission orchestration. It translates text-based operator intent into structured proposals, checks asset capabilities and mission constraints, requires human approval, and executes approved actions in a local simulator. It also models a shared operating picture through synthetic telemetry, sensor observations and in-process swarm messaging. The current release does not connect to physical vehicles or manufacturer systems; its adapter boundary is intended as a starting point for future integration work.
