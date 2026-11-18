# Troubleshooting

## Dashboard does not open

- Confirm the server started without an import error.
- Open <http://127.0.0.1:8000>, matching the port printed by Uvicorn.
- Check `GET /api/health` in a browser or terminal.
- If port 8000 is occupied, use `uvicorn backend.main:app --reload --port 8001` and open port 8001.

## Map shows a grid instead of streets

The grid is the intentional offline schematic fallback. It appears when Leaflet's CDN assets do not load. It remains interactive for placing virtual objects, waypoints and coverage vertices. For a geographic basemap, allow access to the Leaflet assets at `unpkg.com` and public OpenStreetMap standard tile servers. The app does not bundle offline geographic tiles.

## Blank map area

- Open browser developer tools and check Console and Network.
- Confirm `/static/app.js` and `/static/style.css` return HTTP 200.
- Confirm the API's `/api/map/config` and `/api/state` return JSON.
- A blocked external map CDN should show the fallback grid rather than block fleet controls.

## Generate Plan does nothing

- Enter at least a short mission instruction.
- Check the Mission Proposal area and browser Console.
- In offline mode, use explicit commands such as `Send Scout-1 north.` or `Return Scout-1 home.`. The offline parser is intentionally limited.
- Confirm the operator/coordinator link is enabled before approving or rejecting a proposal.

## Map waypoint is rejected

The point must be inside the green operating geofence and outside the red restricted no-go region. Select an available vehicle with navigation capability. Failed, moving or landed vehicles cannot receive a new map waypoint.

## Coverage proposal is rejected

Use a simple convex polygon with three to forty distinct points. Keep the whole shape inside the geofence and outside the restricted zone. Self-intersecting and concave polygons are intentionally rejected by this version. Try a larger lane spacing if the generated route exceeds the waypoint cap.

## Sensor object does not produce observations

- Confirm the object is visible and inside the operating area.
- Choose Easy difficulty for the reproducible demo.
- Check that at least one nearby vehicle has its sensor enabled and a sufficient radius.
- Failed/landed vehicles and vehicles at or below 5% battery do not produce observations.
- Select **Scan now** or wait for the next simulation tick.
- If the radio is disabled, local observations may remain `LOCAL_ONLY` rather than shared.

## No CORROBORATED status

The object must be observed by at least two distinct enabled and available simulated vehicles on the same object revision. Adjust its location/range or use the default test coordinate near `(22, 45)`. Corroboration is a source count, not proof of object identity.

## Blackbox has few samples

Telemetry is recorded on simulation ticks. Leave the dashboard open for a few seconds or trigger `/api/simulation/tick`, then select **Refresh data**. Reset clears historical samples.

## Swarm messages are blocked

Check the global swarm switch, the sender/recipient radio switches, coordination mode, peer mesh and coordinator link. Hybrid mode plus Peer Mesh permits simulated peer delivery during coordinator-link loss. Operator approval still requires the coordinator link.

## Gemini unavailable

The app defaults to Offline. If Gemini is enabled but no key is configured or the API call fails, the planner falls back to deterministic offline behavior. Verify the `.env` values, restart Uvicorn and never put the key into frontend code.

## Stale/corrupt local demo state

Stop the server, back up if needed, remove `data/omnifleet.sqlite3` and any matching `-wal`/`-shm` files, then restart. The app will seed the demo fleet again.
