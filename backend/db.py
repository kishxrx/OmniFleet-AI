import sqlite3, json, os
from pathlib import Path

DB_PATH=Path(os.getenv("OMNIFLEET_DB", Path(__file__).resolve().parent.parent/"data"/"omnifleet.sqlite3"))

def connect():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH); c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
    c.commit(); return c

def save_snapshot(fleet, missions, events, swarm_state=None, sensor_state=None):
    payload={"fleet":{k:v.public() for k,v in fleet.items()},"missions":missions,"events":events[-200:],"swarm":swarm_state or {},"sensors":sensor_state or {}}
    with connect() as c: c.execute("INSERT INTO snapshots(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",(json.dumps(payload),))

def load_snapshot():
    with connect() as c: row=c.execute("SELECT payload FROM snapshots WHERE id=1").fetchone()
    return json.loads(row[0]) if row else None
