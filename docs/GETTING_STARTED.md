# Getting Started

## 1. Prerequisites

- Python 3.10 or newer.
- pip and a terminal.
- A modern browser.
- Optional internet access for Leaflet/OpenStreetMap basemap tiles and Gemini API requests.

The application itself and the schematic map fallback run locally without an LLM key. No Docker, Node build step, database server or GPU is required.

## 2. Install

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## 3. Run

```bash
uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The service exposes `GET /api/health` for a simple health response.

## 4. Optional Gemini configuration

Offline mode is the default. To enable the Gemini Developer API, place the key in the local `.env` file:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Never check `.env` into source control. Do not expose the key in browser JavaScript or screenshots. This version calls the Gemini Developer API; a Vertex service-account JSON file is not a drop-in replacement.

## 5. Data storage and reset

By default, SQLite state is stored in `data/omnifleet.sqlite3`. Override it with `OMNIFLEET_DB` if you want a different location. The app snapshots fleet, missions, recent events, swarm state, sensor objects, observations and blackbox telemetry.

Use the **Reset simulation** icon in the sidebar to restore the deterministic three-vehicle fixture and clear mission/sensor/blackbox history. The UI asks for confirmation. Alternatively, stop the server and remove the SQLite file and its `-wal`/`-shm` files, then restart.

## 6. Demo theatre configuration

| Setting | Default | Notes |
|---|---:|---|
| `OMNIFLEET_THEATRE_NAME` | `Demo Test Range - Bengaluru` | Display name |
| `OMNIFLEET_ORIGIN_LAT` | `12.9716` | Demo WGS84 origin |
| `OMNIFLEET_ORIGIN_LON` | `77.5946` | Demo WGS84 origin |
| `OMNIFLEET_THEATRE_WIDTH_M` | `2000` | Side length used for local conversion |

Coordinates are illustrative. Changing the origin only relocates the demo display; it does not make the simulator suitable for real navigation.

## 7. Development checks

Install optional test tools:

```bash
pip install -r requirements-dev.txt
```

Backend and static checks:

```bash
python -m pytest -q
python -m compileall -q backend tools tests
node --check frontend/app.js
```

Browser interaction acceptance (optional):

```bash
playwright install chromium
python tools/browser_acceptance.py
```

See [Testing & Verification](TESTING_AND_VERIFICATION.md) for the scope of these checks.
