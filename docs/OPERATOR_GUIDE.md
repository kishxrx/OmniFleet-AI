# Operator Guide

This guide describes the controls in the OmniFleet dashboard. All vehicle actions are simulation-only. A map click, sensor observation, message, or AI proposal does not bypass the server-side validation and approval rules.

## Command overview

The top cards summarize registered assets, active missions, vehicles in motion and fleet readiness. **Refresh** asks the UI to reload current API state. The clock is display-only. The `?` button opens the operator quick-reference dialog.

## Mission Control

1. Enter an instruction or choose one of the prompt examples.
2. Select **Generate plan**.
3. Review the mission proposal, agent trace and safety checks.
4. Select **Approve & execute** or **Reject proposal**.

Useful offline-mode prompts:

```text
Send Scout-1 north and Scout-2 east. Keep Relay-1 stationary.
Return Scout-1 home.
Send Scout-2 west.
```

The offline command parser supports a limited set of explicit commands. It is not a general-purpose natural-language understanding system. Optional Gemini planning broadens interpretation but its output is still treated as an untrusted proposal and checked by deterministic policy.

## Operational map

### Layers

- **Routes:** show active/approved route lines.
- **Zones:** show the operating geofence and restricted polygon.
- **Labels:** show base and restricted-zone labels.
- **Sensor rings:** show illustrative isotropic sensor radii.
- **Comm range:** show nominal communication radii. These circles do not constrain the logical message bus.
- **Test objects:** show operator-created virtual objects.
- **Observations:** show synthetic observations and source status.

With Leaflet and tile services available, the main view shows the geographic basemap. If Leaflet cannot load, the interactive schematic canvas is displayed. Both modes support local-coordinate placement tasks.

### Waypoint tasking

1. Choose an available vehicle from the selector.
2. Select **Place waypoint**.
3. Click inside the green operating boundary and outside the restricted area.
4. Review the generated proposal in Mission Control.
5. Approve or reject it.

The server converts displayed WGS84 coordinates into normalized local simulation coordinates and validates the point again. Invalid or restricted coordinates are rejected.

### Area coverage

1. Choose a lane spacing.
2. Select **Draw area** and click at least three boundary points.
3. Select **Generate sectors** to submit the polygon.
4. Review the number of sectors, waypoints, reserve vehicle, and safety summary.
5. Approve or reject the proposal.

Use a simple **convex** polygon entirely inside the operating geofence and outside the restricted zone. This version rejects concave and self-intersecting boundaries. **Clear** removes the in-progress drawing; selecting Draw area again cancels or restarts drawing.

## Fleet assets and failure simulation

The fleet panel lists vehicle type, readiness, location and battery. **Inject outage** marks a vehicle as failed. If an active mission is affected, the Mission Monitor creates a recovery proposal when a compatible available vehicle exists. Review and approve the recovery separately. The simulator does not perform real fault diagnosis.

## Sensor Intelligence & Test Objects

### Place a virtual object

1. Set a label, category, difficulty and visibility.
2. Select **Place on map** (or **Place test object** in the map toolbar).
3. Click inside the operating geofence, away from the no-go polygon.
4. Select **Scan now**.

The sensor model checks whether each enabled, available simulated vehicle is within its configured circular footprint. A scan is repeated automatically on simulation ticks.

### Manage objects

- **Move:** select the object's Move button, then click its new map position.
- **Hide / Show:** controls whether future scans may observe it. Existing historical observations remain.
- **Remove:** removes it from active map state while preserving historical records.
- **Difficulty:** scales the effective simulated radius (Easy 100%, Medium 82%, Hard 64%).

### Vehicle sensor controls

- Sensor enabled switch: allows/prevents new observations.
- Sensor radius slider: adjusts the illustrative sensor circle and scan range.
- Comm range slider: adjusts only the displayed nominal comm circle. It does not implement RF propagation.

### Observation ledger

Each record shows the source vehicle, object revision, timestamp, distance, synthetic confidence score, modality and whether the observation was shared. `CORROBORATED` means two or more distinct simulated sources observed the same object revision. It is not object identity proof, an independently audited sensor fact, or a calibrated probability.

## Blackbox Analytics

1. Choose a vehicle.
2. Select **Refresh data** to retrieve its bounded telemetry window.
3. Inspect sample count, latest battery, peak speed, distance across the returned window and latest status.
4. Scrub the timeline to inspect a sample.
5. Select **Show sample on map** to place the replay marker.
6. Select **Play replay**; the same control becomes **Pause replay**.

The replay uses recorded simulation samples. A sample describes the state captured on a simulation tick; it is not live sensor telemetry from a physical aircraft.

## Swarm Intelligence & Communications

### Network policy

- **Swarm communications:** master enable/pause switch.
- **Coordination mode:** `centralized` routes peer traffic via the coordinator; `hybrid` allows simulated direct peer delivery when Peer Mesh is enabled.
- **Peer mesh:** turns the simulated vehicle-to-vehicle route on/off.
- **Coordinator link:** models operator/central-coordinator connectivity.
- **Latency (sim ticks):** queues deliveries for 0–10 simulation ticks; the link is checked again when the queue expires.
- **Packet loss (%):** deterministically drops 0–100% of message-recipient deliveries for repeatable tests.
- **Apply network policy:** saves the selected configuration.

### Vehicle radios

Each vehicle radio switch can be enabled or disabled independently. A radio-off vehicle cannot send or receive peer messages, but its local simulated sensor observation can still be recorded. Each recipient maintains its own last-known peer state. The coordinator view and a peer view update only when the relevant heartbeat is delivered, so disconnected recipients retain stale last-known information during a link outage.

### Operator tools

- **Request fleet status:** sends a status request and collects reachable status reports.
- **Test peer link:** sends a test message from the selected sender to recipient and returns an acknowledgement when delivered.
- **Broadcast to fleet:** sends informational text to all or a selected vehicle. It is not an executable vehicle command.
- **Simulate shared detection:** submits a structured simulated detection. Eligible peers may send task offers, resulting in a pending inspection proposal. Approval still requires the coordinator/operator link.
- **Scan route conflicts:** predicts synchronized closest approach over the active route and queued waypoints. The simulator separately applies a per-tick separation guard, clips a priority vehicle at the clearance boundary, and routes a yielding peer laterally when possible. If safe movement cannot be resolved, the vehicle enters a safe hold and its mission degrades. These are illustrative 2-D heuristics, not validated collision avoidance.

### Reproducible peer-negotiation scenario

1. Set mode to Hybrid, enable Peer Mesh and Coordinator Link, then apply.
2. Submit a detection from Scout-1 at a valid point such as local `(70, 55)`.
3. Inspect `DETECTION_EVENT`, `TASK_REQUEST` and `TASK_OFFER` in the communication stream.
4. Turn Coordinator Link off while leaving Hybrid + Peer Mesh on; submit another detection. Peer negotiation may still produce a proposal.
5. The proposal must remain pending. Restore the coordinator link before approving or rejecting it.

## Global controls

- **Refresh:** reloads dashboard state.
- **Reset simulation:** after confirmation, re-seeds the three demo vehicles and clears mission, sensor, swarm and blackbox history.
- **Operator help (`?`):** opens the quick-reference dialog with section links.

## Suggested founder-interview demonstration

Show the system in this order: natural-language mission proposal and approval; map waypoint or area coverage; create a virtual object and show two-source observation sharing; inspect the peer message stream; inject a failure and approve recovery; replay the blackbox record. Explain clearly that all of this is an offline software simulation, not a deployed drone system.


## Display-only dashboard elements

This build has one local workspace. The workspace badge is not a selector; the muted **Agent orchestration** and **Analytics** system entries are roadmap placeholders; and **Latest events** is a static heading rather than a filter. Fleet cards, agent status, metrics, legends and the clock are read-only. The complete distinction between actionable controls and display-only elements is documented in the [Control Wiring & QA Matrix](CONTROL_WIRING.md).
