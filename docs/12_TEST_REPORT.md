# OmniFleet AI v0.9.2 — Testing & Verification Report

**Verification date:** 8 November 2026  
**Scope:** Freshly extracted v0.9.2 project, isolated temporary SQLite databases, pytest suite, actual FastAPI application, Chromium browser and a separately running Uvicorn HTTP server.  
**Mode:** Offline simulation. No Gemini API key, physical vehicle, camera, real radio or autopilot was used.

## Summary

| Check | Result |
|---|---:|
| Automated pytest suite | **77/77 passed** |
| Python compilation | PASS |
| JavaScript syntax | PASS |
| Standard browser interaction groups | **13/13 passed** |
| Standard browser API requests | **192 HTTP 200** |
| Dedicated automation browser run | **PASS** |
| Dedicated automation browser API requests | **131; 0 HTTP errors** |
| Browser JavaScript/page errors | **0** |
| Live Uvicorn HTTP workflow | **PASS** |
| Live Uvicorn successful HTTP responses | **210 HTTP 200 + 1 expected HTTP 409** |
| Live delayed-negotiation mission | **COMPLETED after 95 simulation ticks** |
| Live selected inspector Blackbox | **100 telemetry samples** |

## Commands executed

```bash
python -m compileall -q backend tools tests
node --check frontend/app.js
python -m pytest -q
python tools/browser_acceptance.py
python tools/automation_browser_acceptance.py
```

A separate Uvicorn process was started on `127.0.0.1` with a temporary SQLite database. The live-server scenario enabled hybrid peer mode, disabled the coordinator link, configured two simulation ticks of latency, created a virtual object, obtained two independent observations, waited for delayed `TASK_REQUEST` and `TASK_OFFER` delivery, verified that approval returned the expected HTTP 409 while the coordinator was offline, restored the coordinator link, approved the proposal, and waited for mission completion. The mission completed after 95 simulation ticks; delayed coordination was cleared, and the selected Scout-2 blackbox contained 100 telemetry samples. At proposal time the message stream contained one `TASK_REQUEST`, one `TASK_OFFER` and six `ACKNOWLEDGEMENT` messages. The server returned 210 successful HTTP 200 responses and one expected HTTP 409; the rejected approval was an intentional safety check.

## Regression and safety coverage

The 77 pytest cases cover:

- Heterogeneous fleet seeding, mission planning, deterministic policy checks, approval/rejection, mission monitoring and recovery.
- SI movement conversion: 4 m/s for one simulated second moves 0.2 local units in the default 2 km / 100-unit theatre.
- Seeded vehicle placement outside restricted geometry.
- Safe routes around restricted polygons, fixed structures and the current moving virtual obstacle.
- Runtime moving-obstacle replanning and completion without entering the obstacle polygon.
- Atomic rejection of multi-vehicle plans whose final positions violate minimum separation.
- Head-on and perpendicular crossing trajectories. The runtime guard clips movement at the 2-local-unit clearance boundary, applies deterministic right-of-way, schedules a lateral peer detour, and keeps the tested pair at or above the configured separation while both complete.
- Impossible occupied destinations and persistent blocks transitioning to safe hold instead of endless mission execution.
- Time-synchronized trajectory conflict prediction across active targets and queued waypoints, including a geometric crossing that occurs at different times and should not be reported as a predicted conflict.
- Battery recovery when return-home energy is insufficient, emergency landing for an aircraft, safe hold for a ground robot, rejection of unsafe emergency locations, acceleration-aware route energy and protected reserve calculation.
- Centralized/hybrid routing, radio toggles, symmetric peer range, recipient-specific knowledge, coordinator outage, delayed delivery, acknowledgements, deterministic packet loss and persisted pending coordination.
- Delayed sensor corroboration, proposal retry after communication recovery, duplicate suppression after successful proposal creation, and delayed task negotiation through to a pending-approval proposal.
- Sensor object lifecycle, synthetic sensing, local-only observations, multi-source corroboration and Blackbox persistence.
- Public page/static asset delivery and API validation/error contracts.

## Browser verification

The standard Chromium script exercised 13 interaction groups against the shipped HTML/CSS/JavaScript and FastAPI endpoint logic through an in-process TestClient bridge. It covered dashboard startup, help/navigation, map overlays, prompts, waypoint planning, coverage drawing, object placement/scanning/editing, sensor configuration, Blackbox replay, swarm controls, mission approval/recovery, reset and mobile overflow. All 192 browser-triggered API calls returned HTTP 200; no page, JavaScript or console errors were recorded.

The dedicated Chromium workflow exercised object placement → sensor scan → two-source corroboration → peer task request/offer → pending approval during coordinator outage → coordinator restoration → operator approval → simulated movement → mission completion. Result: Scout-2 selected, mission `COMPLETED`, 131 browser API requests, zero HTTP errors, zero browser errors and 28 Scout-2 Blackbox samples.

The browser bridge uses TestClient because the browser sandbox cannot directly navigate to the local TCP server. The separate Uvicorn test independently verifies the real HTTP server path.

## Static checks

- `python -m compileall -q backend tools tests` completed successfully.
- `node --check frontend/app.js` completed successfully.
- The project ZIP passed archive integrity checks.
- Internal Markdown links were checked against files included in the project.
- Browser acceptance found no page exceptions, console errors or unexpected HTTP failures.

## What these tests do not establish

- No live Gemini API behavior was tested; offline planning was used.
- No camera feed, computer vision, object classification or real sensor was used. Sensor detections remain synthetic geometric observations.
- The moving obstacle is a scripted polygon with deterministic bounded motion. Vehicles do not discover or perceive obstacles from imagery or sensor data.
- Vehicle separation, route planning and time-synchronized conflict prediction are simplified 2-D simulation heuristics. They are not formally verified, continuous-time, 3-D or validated collision-avoidance algorithms.
- Battery and return-energy estimates use a simplified deterministic drain model and are not calibrated to a real vehicle.
- Communication range is a geometric reachability gate. Latency and packet loss are deterministic in-process impairment controls, not RF propagation or stochastic network emulation.
- No physical drone, camera, real radio, autopilot, PX4 SITL or hardware-in-the-loop test was performed. The PX4 adapter refuses dispatch.
- No penetration test, production load test, multi-user concurrency test or security review was performed. The demo has no authentication layer.

## Reproduce

Follow [Getting Started](GETTING_STARTED.md), install `requirements-dev.txt`, then run the commands above. Browser verification requires Playwright Chromium (`playwright install chromium`). Tests use temporary databases and do not alter an operator's persistent simulation database.
