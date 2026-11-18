# Agent Design — v0.9.2

| Role | Responsibility | Execution authority |
|---|---|---|
| Mission Planner | Translate operator instruction into structured actions | Proposal only |
| Fleet Coordinator | Review assignment intent and coordinate the fleet | Proposal coordination only |
| Safety & Policy | Deterministically validate IDs, actions, mission capabilities, availability, coordinates, geofence/no-go and plan bounds | May reject; never dispatches |
| Execution Agent | Dispatch approved actions through the configured adapter | Simulator only |
| Mission Monitor | Evaluate completion/degradation; create recovery proposals | Proposal only |
| Swarm Network | Route allowlisted messages, maintain shared state, collect offers/acks | Information transport only |
| Sensor Simulation | Generate synthetic observations from virtual object/range geometry | Observation records only |

## LLM boundary

When Gemini is configured, Planner and Coordinator receive separate role-specific requests. The offline parser/coordinator are deterministic fallbacks. LLM content is untrusted input: deterministic safety validation runs before an operator can approve a proposal. No LLM output bypasses the approval gate.

## Not fully autonomous

This prototype does not host an independent reasoning LLM inside each simulated vehicle. Vehicle-level task offers and message responses are deterministic. Hybrid peer negotiation is a bounded in-process simulation, not a decentralized consensus algorithm.
