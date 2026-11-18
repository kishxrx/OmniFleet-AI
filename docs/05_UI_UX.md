# UI / UX — OmniFleet AI 0.7.0

## Visual direction

An original enterprise operations console combining an Aleni-inspired clean visual hierarchy, a Mass Zero-inspired map-first operational view and Skydio-inspired fleet readiness, approvals and audit workflows. It is not a pixel-for-pixel reproduction of any reference product.

## Layout

- Dark navigation rail and light operations workspace.
- Fleet summary, operational map and mission tasking in the primary workspace.
- Fleet assets, agent activity and simulated failure controls in the right rail.
- Sensor Intelligence & Test Objects.
- Blackbox Analytics.
- Swarm Intelligence & Communications.
- Operations activity and audit stream.
- Responsive layout for narrower viewports.

## Main interactive controls

- Mission instruction, prompt examples, generate, approve and reject.
- Map vehicle selector, waypoint tasking, map fit and seven layer toggles.
- Coverage draw/cancel/clear, spacing selector and proposal generation.
- Failure injection buttons.
- Sensor object placement and object list Move/Hide/Show/Remove actions.
- Sensor enable, sensor radius and nominal communication radius controls.
- Blackbox vehicle selection, refresh, replay range, play/pause and show-on-map.
- Swarm enable, mode, peer mesh, coordinator link, per-vehicle radio, status request, peer test, broadcast, detection simulation and conflict scan.
- Reset with confirmation and manual refresh.
- Operator quick-reference dialog.

## Mapping behavior

Leaflet 1.9.4 and the public OpenStreetMap tile service provide the geographic view when online. When Leaflet assets are unavailable, a canvas fallback provides an interactive local schematic view. The fallback is not a geographic street map. Both views share the server-side local coordinate model.

## Accessibility and validation

Interactive controls have stable DOM IDs or data attributes, JavaScript references map to existing HTML IDs, the operator guide is a native dialog, and button states reflect pending/disabled mission states. The acceptance runner checks key click paths and a mobile-width no-overflow condition. This is not a formal accessibility audit.
