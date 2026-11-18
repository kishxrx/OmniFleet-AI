# Architecture decision records

- ADR-001 Modular monolith: smallest testable delivery for a low-resource demo.
- ADR-002 Custom 2D local-coordinate simulator: deterministic, dependency-light and explicit about non-GPS semantics.
- ADR-003 Gemini optional/offline-first: live provider outages cannot block the demo.
- ADR-004 Human approval gate: LLM output never directly executes.
- ADR-005 SQLite snapshot persistence: simple restart recovery without a database service.
- ADR-006 PX4 adapter remains non-operational: real command paths require SITL, coordinate calibration, reviewed failsafes and separate safety validation.
