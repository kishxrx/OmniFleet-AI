# HTTP API Reference

Base URL when running locally: `http://127.0.0.1:8000`. JSON request bodies are used for mutating endpoints unless noted. Error responses use FastAPI's standard error format; the main deliberate status codes are `404` (unknown resource), `409` (state/approval/link conflict) and `422` (invalid input or safety validation).

## Health, state and configuration

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Version and adapter health |
| GET | `/api/state` | Fleet, missions, summaries, events and provider |
| GET | `/api/events` | Recent operational event records |
| GET | `/api/map/config` | Theatre origin, map bounds, geofence and no-go zones |
| POST | `/api/fleet/seed` | Reset fleet, missions, swarm, sensors and blackbox to demo defaults |

## Missions and simulation

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/plan` | Build a mission proposal from `{ "instruction": "..." }` |
| POST | `/api/missions/{mission_id}/approve` | Revalidate safety and dispatch to the simulator |
| POST | `/api/missions/{mission_id}/reject` | Reject a pending proposal |
| POST | `/api/map/waypoint` | Create a map-selected waypoint proposal |
| POST | `/api/missions/coverage/plan` | Generate area-coverage sectors and sweep routes |
| POST | `/api/vehicles/{vehicle_id}/fail` | Inject a simulated vehicle failure and request recovery proposals |
| POST | `/api/simulation/tick` | Advance vehicle simulation, mission monitor, swarm heartbeat, sensor scan and blackbox capture |

Map waypoint example:

```json
{
  "vehicle_id": "scout-1",
  "latitude": 12.9716,
  "longitude": 77.5946
}
```

Coverage example (coordinates must map to a safe convex polygon in the demo geofence):

```json
{
  "polygon": [
    {"latitude": 12.9700, "longitude": 77.5940},
    {"latitude": 12.9700, "longitude": 77.5950},
    {"latitude": 12.9708, "longitude": 77.5950},
    {"latitude": 12.9708, "longitude": 77.5940}
  ],
  "lane_spacing_m": 80
}
```

## Swarm communications

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/swarm/state` | Current configuration, radio states, messages and shared knowledge |
| PUT | `/api/swarm/config` | Update `enabled`, `coordination_mode`, `peer_mesh_enabled`, `coordinator_link_enabled`, `network_latency_ticks` (0–10) and `packet_loss_pct` (0–100) |
| PUT | `/api/swarm/vehicles/{vehicle_id}/radio` | Set `{ "enabled": true }` or false |
| POST | `/api/swarm/broadcast` | Send informational message and optional recipient list |
| POST | `/api/swarm/status-request` | Ask reachable vehicles for status reports |
| POST | `/api/swarm/peer-test` | Send a peer connectivity test |
| POST | `/api/swarm/detections` | Broadcast a simulated detection and gather inspection offers |
| POST | `/api/swarm/conflicts/check` | Report close active destinations |

Configuration example:

```json
{
  "enabled": true,
  "coordination_mode": "hybrid",
  "peer_mesh_enabled": true,
  "coordinator_link_enabled": true
}
```

Detection example:

```json
{
  "source_vehicle_id": "scout-1",
  "x": 70,
  "y": 55,
  "label": "Demo observation",
  "confidence": 0.9
}
```

## Sensor intelligence and virtual objects

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sensors/state` | Active objects, sensor settings, observations and overlap summary |
| POST | `/api/sensors/objects` | Create a virtual map object |
| PUT | `/api/sensors/objects/{object_id}` | Move, hide/show or update object attributes; increments revision |
| DELETE | `/api/sensors/objects/{object_id}` | Remove object from active map state and retain event history |
| PUT | `/api/sensors/vehicles/{vehicle_id}` | Change sensor-enabled, sensor-range or nominal comm-range settings |
| POST | `/api/sensors/scan` | Trigger a synthetic scan and evaluate sensor-to-coordination automation; returns any new pending proposals |
| GET | `/api/sensors/automation` | Read automatic inspection policy |
| PUT | `/api/sensors/automation` | Configure `enabled`, `min_confidence` and `min_sources` |

Create object example:

```json
{
  "x": 22,
  "y": 45,
  "label": "Test Object A",
  "category": "marker",
  "difficulty": "easy",
  "visible": true
}
```

Coordinates for objects are normalized local simulation coordinates (0–100), not latitude/longitude. Category values: `marker`, `vehicle`, `person`, `structure`, `other`. Difficulty: `easy`, `medium`, `hard`.

## Blackbox

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/blackbox?vehicle_id=scout-1&limit=180` | Bounded telemetry sample window and associated events |
| GET | `/api/blackbox/events?vehicle_id=scout-1&limit=100` | Bounded event history |

`vehicle_id` may be omitted for the all-vehicle telemetry stream. Limits are bounded by the API validation layer. Unknown vehicle identifiers return 404.

## Message types

The allowlisted simulated swarm protocol is declared in `backend/swarm.py`. It includes heartbeat, position and battery updates, availability, intent, task request/offer, detection, sensor observation, route conflict, emergency alert, acknowledgement, status request/report, operator announcement and peer test message types.

## Operational notes

- The endpoints mutate one local simulation process and persist a SQLite snapshot; they are not a multi-user production API.
- There is no authentication or authorization layer. Do not expose it to an untrusted network.
- The PX4 adapter is deliberately non-operational. No endpoint can send MAVLink or physical flight commands.
