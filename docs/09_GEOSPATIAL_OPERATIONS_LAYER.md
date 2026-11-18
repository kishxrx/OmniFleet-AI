# Geospatial Operations Layer — v0.5.0

## Purpose
Replace the illustrative 0–100 canvas as the primary operator view with a geographic common operating picture while preserving the deterministic local simulation model.

## Map stack
- Leaflet 1.9.4 for pan, zoom, layers, markers, polylines, popups and click-to-task.
- OpenStreetMap standard tiles with visible attribution.
- A local schematic fallback when Leaflet CDN assets are unavailable.

## Coordinate model
- Display coordinates: WGS84 latitude/longitude.
- Simulation coordinates: normalized local theatre coordinates `x,y ∈ [0,100]`.
- Default theatre origin: 12.9716° N, 77.5946° E (illustrative demo location near Bengaluru).
- Default theatre width: 2,000 m × 2,000 m.
- Conversion: small-area equirectangular approximation using the origin latitude to scale longitude.
- This conversion is explicitly not navigation-grade and must not be used to command real aircraft.

## Operator flow
1. Select an available vehicle in the map tasking control.
2. Activate **Place waypoint**.
3. Click a location on the map.
4. Browser sends WGS84 latitude/longitude to `POST /api/map/waypoint`.
5. Backend converts to local theatre coordinates.
6. Backend rejects points outside the operating geofence or inside a restricted no-go polygon.
7. Backend creates a `PENDING_APPROVAL` mission.
8. Operator approves or rejects through the existing mission approval gate.
9. On approval, the simulated adapter dispatches the local-coordinate waypoint.

## Safety boundaries
- Geofence and no-go checks are server-side.
- Frontend map bounds and visual overlays are not trusted for authorization.
- Map-created missions are pending approval; clicking the map never directly moves an asset.
- No GPS receiver, telemetry transport, MAVLink, PX4 or physical hardware is connected.

## API
- `GET /api/map/config`: origin, bounds, theatre width, geofence, restricted polygons and projection note.
- `POST /api/map/waypoint`: `{vehicle_id, latitude, longitude}` -> pending mission proposal or validation error.
- `GET /api/state`: now includes derived `latitude`, `longitude`, `target_latitude`, and `target_longitude` for each vehicle.

## Operational limitations
- Basemap assets are loaded from public CDN/tile services and require internet access.
- The offline fallback remains interactive but is a schematic local grid, not a street map.
- Default map origin is demo configuration, not user location.
- Replace the local projection with a suitable geodetic library and surveyed theatre configuration before any real-world integration.
