# API and data contracts

- `GET /api/health` — service and adapter health.
- `GET /api/state` — fleet, missions, events and summary.
- `GET /api/events` — recent audit events.
- `GET /api/map/config` — demo theatre origin, bounds, geofence and no-go polygons.
- `POST /api/map/waypoint` — `{ "vehicle_id": "scout-1", "latitude": 12.9716, "longitude": 77.5946 }`; returns a pending-approval waypoint mission.
- `POST /api/fleet/seed` — reset deterministic demo fleet and mission history.
- `POST /api/plan` — `{ "instruction": "..." }`; returns a pending or rejected mission.
- `POST /api/missions/{id}/approve` — dispatch after human approval.
- `POST /api/missions/{id}/reject` — reject a pending proposal.
- `POST /api/vehicles/{vehicle_id}/fail` — inject a demo failure and return recovery proposal(s).
- `POST /api/simulation/tick` — advance the local simulation and mission monitor.

Simulation vehicle coordinates remain normalized local units in the 0–100 range. `GET /api/state` additionally derives approximate WGS84 `latitude`, `longitude`, `target_latitude` and `target_longitude` fields for the map. SQLite stores the local fleet snapshot, mission records and recent event stream. The geospatial conversion is a small-area demo approximation, not a navigation-grade projection.

## Swarm communication API (v0.6.0)

- `GET /api/swarm/state` — routing configuration, link status, per-vehicle radio switches, recent messages and shared knowledge.
- `PUT /api/swarm/config` — update `{ enabled?, coordination_mode?: "centralized"|"hybrid", peer_mesh_enabled?, coordinator_link_enabled?, network_latency_ticks?: 0..10, packet_loss_pct?: 0..100 }`. Latency queues simulated message delivery by tick; packet loss is a deterministic message-recipient drop control.
- `PUT /api/swarm/vehicles/{vehicle_id}/radio` — `{ "enabled": true|false }`.
- `POST /api/swarm/broadcast` — `{ "message": "...", "recipients": ["scout-1"]? }`; announcement messages are informational and never executable.
- `POST /api/swarm/status-request` — ask reachable vehicles for structured status reports.
- `POST /api/swarm/peer-test` — `{ "sender_vehicle_id": "scout-1", "recipient_vehicle_id": "scout-2", "message": "..." }`.
- `POST /api/swarm/detections` — `{ "source_vehicle_id": "scout-1", "x": 64, "y": 58, "label": "...", "confidence": 0.92 }`; broadcasts the event, gathers eligible `TASK_OFFER` messages and creates a pending-approval inspection proposal if an eligible peer is reachable.
- `POST /api/swarm/conflicts/check` — scans active target proximity and broadcasts any potential conflict alert.

The allowed message types are defined in `backend/swarm.py`. Message envelopes include sender, recipients, delivered recipients, timestamp, type, payload, status and routing channel. These APIs control the simulator's in-process protocol only.


## v0.7 Sensor sandbox and blackbox contracts

Sensor object create/update requests use local simulation coordinates (0–100), an allowlisted category (`marker`, `vehicle`, `person`, `structure`, `other`), difficulty (`easy`, `medium`, `hard`) and a visibility switch. Server-side validation rejects out-of-geofence and no-go-zone coordinates. Object revisions cause fresh observation keys, while previous observations remain in the history.

Sensor settings expose `sensor_enabled`, `sensor_range_m` (50–1000) and `comm_range_m` (100–2000). Ranges are simulation/display values. `SENSOR_OBSERVATION` is a structured, allowlisted swarm message containing object/revision identifiers, location, confidence score, modality and source provenance.

Blackbox reads return bounded per-vehicle telemetry samples and event records. Telemetry is captured on each simulation tick and persisted with the SQLite snapshot.
