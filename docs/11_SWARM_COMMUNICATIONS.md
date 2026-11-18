# Swarm Intelligence & Communications — v0.9.2

## Purpose

The swarm layer is a deterministic, in-process simulation of structured communication between heterogeneous simulated vehicles and an operator/coordinator. It exchanges synthetic telemetry, intentions, acknowledgements, task offers, detections and alerts. It does not create a radio network or hardware control path. Every movement remains subject to deterministic backend policy validation and explicit human approval.

## Routing modes

- `centralized`: vehicle-to-vehicle traffic is represented as coordinator-relayed and depends on the coordinator link.
- `hybrid`: when peer mesh is enabled, direct vehicle-to-vehicle messages can still be delivered while the coordinator link is offline. Operator/coordinator communication still requires the coordinator link.

Direct peer delivery requires both vehicles to be within the smaller of their configured nominal communication radii (symmetric range rule). Separation is calculated from current local simulation positions using the theatre scale (20 m per local unit by default). This is a geometric reachability check, not RF propagation.

## Network impairment controls

The Swarm panel exposes two repeatable test controls:

| Setting | Range | Behaviour |
|---|---:|---|
| `network_latency_ticks` | 0–10 | Queues a delivery for the configured number of simulation ticks; link and radio state are rechecked at delivery time |
| `packet_loss_pct` | 0–100 | Applies deterministic message-recipient loss so a scenario can be reproduced |

Queued messages retain their delivery state in the SQLite snapshot. An acknowledgement is generated only after the original message is delivered. A failed delivery is recorded as blocked/dropped rather than silently treated as successful. These controls are intentionally deterministic; they are not physical network emulation. They do not model bandwidth, RF propagation, terrain, antenna patterns, interference, encryption, authentication, QoS, or multi-hop routing.

## Message protocol

Messages use a fixed allowlist and a JSON-object payload. Supported types include:

- `HEARTBEAT`, `POSITION_UPDATE`, `BATTERY_UPDATE`, `AVAILABILITY_UPDATE`
- `INTENT_BROADCAST`, `ACKNOWLEDGEMENT`
- `TASK_REQUEST`, `TASK_OFFER`
- `DETECTION_EVENT`, `ROUTE_CONFLICT`, `EMERGENCY_ALERT`
- `STATUS_REQUEST`, `STATUS_REPORT`, `OPERATOR_ANNOUNCEMENT`, `PEER_TEST`, `SENSOR_OBSERVATION`

Each envelope contains an ID, UTC timestamp, sender, intended recipients, delivered recipients, message type, payload, delivery status and channel. Unknown message types are rejected. Operator announcements are explicitly marked `executable: false` and are never parsed as vehicle commands.

## Recipient-specific fleet knowledge

The coordinator has its own last-known fleet picture. Each vehicle also has a separate last-known table for information it received from peers. A heartbeat changes the relevant table only after the message is actually delivered. Disconnected vehicles therefore retain stale last-known information rather than silently sharing the live global simulator state. The dashboard operator view can still display the simulator's actual state; that is separate from what each peer knows.

## Collaborative detection and task offers

1. A synthetic scan records observations for visible virtual objects inside enabled sensor footprints.
2. When automation is enabled and an object revision has enough distinct qualifying sources (defaults: two sources, minimum confidence 0.65), the retained observation history can trigger a `DETECTION_EVENT`, including when corroboration arrives on different scans/ticks.
3. The reporting source broadcasts a detection and requests inspection assistance from eligible peers.
4. Eligible peers return `TASK_OFFER`. Under non-zero network latency, the coordinator waits for delayed delivery before selecting an offer.
5. The nearest eligible offer is selected and a `PENDING_APPROVAL` proposal is created. Failed/blocked negotiations use bounded retries; duplicate suppression is committed only after a valid proposal exists.
6. The operator must restore coordinator connectivity if required, then explicitly approve or reject. Sensor automation never dispatches a vehicle directly.

For the seeded demonstration fleet, Scout-1 and Scout-2 support `inspect`; Relay-1 supports `ground_inspection`. The planar coverage capability is generic simulation metadata and does not imply that real aerial and ground platforms are interchangeable.

## Trajectory-conflict scanning

The conflict endpoint predicts synchronized positions over a bounded time horizon using current speed, configured acceleration, active target and queued route waypoints. It reports minimum predicted separation and time-to-closest-approach. This avoids flagging a simple geometric crossing when the vehicles are predicted to pass at different times. The runtime movement guard separately checks each simulation tick and can yield, clip to a clearance boundary, route around a peer or safe-hold when no route can be established.

## Operator controls

The Swarm Intelligence panel provides network pause/resume, centralized/hybrid mode, peer-mesh toggle, coordinator-link toggle, per-vehicle radios, operator broadcast, status request, peer test, synthetic detection injection, latency/packet-loss controls, trajectory conflict scan and a live message stream.

## Safety boundaries

- Communication messages are not executable commands.
- Detection reports must come from a known, communicating, non-failed vehicle and fall within the demo operating area.
- Inspection task offers are capability-, availability-, communication- and battery-filtered.
- The resulting inspection mission is revalidated by the backend and stays pending until operator approval.
- The network is in-process and single-server. It is not a production broker or distributed service.
- No MQTT, ROS 2 DDS, MAVLink, PX4, radio, or physical vehicle integration is included.
