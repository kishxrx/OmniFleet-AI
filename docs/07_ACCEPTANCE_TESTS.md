# Acceptance Test Matrix — v0.9.2

- [x] Dashboard serves HTML, CSS and JavaScript assets.
- [x] Dashboard boot renders three seeded heterogeneous assets.
- [x] All seven map layer toggles update UI state without JavaScript exceptions.
- [x] Mission prompt examples populate the command composer.
- [x] Mission proposal can be reviewed, approved or rejected.
- [x] Map fit, vehicle selection and map waypoint tasking work in the fallback canvas.
- [x] Waypoint proposals pass/reject based on geofence, no-go and asset availability.
- [x] Coverage draw, cancel, clear, spacing, plan and reject paths work.
- [x] Area planner validates convex polygons, sector generation and route constraints.
- [x] Vehicle failure can create a compatible recovery proposal requiring a second approval.
- [x] Swarm network mode, peer mesh, coordinator link and global enable controls work.
- [x] Per-vehicle radio switches work.
- [x] Peer link, status request, informational broadcast and simulated detection controls work.
- [x] Coordinator-link outage and hybrid peer negotiation are covered by backend tests.
- [x] Route conflict scan returns a clearly labelled proximity heuristic.
- [x] Virtual object placement, move, hide/show and delete work.
- [x] Sensor scan records observations and supports same-revision multi-source corroboration.
- [x] Sensor settings enforce configured bounds.
- [x] Blackbox refresh, vehicle selector, replay scrub, play/pause and map marker work.
- [x] SQLite snapshot restores fleet, mission, swarm and sensor/blackbox state.
- [x] Reset asks for confirmation and restores the seeded demo state.
- [x] Unknown IDs, malformed values and restricted coordinates return deliberate errors.
- [x] Operator help dialog opens, closes and navigates to guide sections.
- [x] Responsive viewport check passes at 390 CSS pixels.
- [x] PX4 placeholder refuses command dispatch.

Latest run: 44 pytest tests passed; 13 browser interaction groups passed; 181 browser-triggered API calls returned HTTP 200; zero browser page/console errors. See [Testing & Verification](TESTING_AND_VERIFICATION.md).
