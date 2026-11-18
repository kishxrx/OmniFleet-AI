"""Deterministic sensor-footprint and blackbox simulation.

This module creates synthetic observations from configured sensor circles and
virtual test objects. It does not process camera imagery, identify real-world
objects, or model validated sensor performance.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import hypot
from uuid import uuid4

from .geospatial import THEATRE_WIDTH_M, in_geofence, in_no_go_zone

DIFFICULTY_FACTOR = {"easy": 1.0, "medium": 0.82, "hard": 0.64}
CATEGORY_ALLOWLIST = {"marker", "vehicle", "person", "structure", "other"}
MAX_OBJECTS = 60
MAX_OBSERVATIONS = 800
MAX_TELEMETRY = 1800
MAX_EVENTS = 600


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SensorSimulation:
    def __init__(self):
        self.settings: dict[str, dict] = {}
        self.objects: list[dict] = []
        self.observations: list[dict] = []
        self.telemetry: list[dict] = []
        self.events: list[dict] = []
        self.tick_count = 0
        self._observed_keys: set[str] = set()
        self._automated_keys: set[str] = set()
        self._automation_retry_after: dict[str, int] = {}
        self.automation = {"enabled": True, "min_confidence": 0.65, "min_sources": 2}

    def ensure_fleet(self, fleet):
        defaults = {
            "quadrotor": {"sensor_enabled": True, "sensor_range_m": 450.0, "comm_range_m": 1000.0},
            "fixed-wing": {"sensor_enabled": True, "sensor_range_m": 600.0, "comm_range_m": 1200.0},
            "ground_robot": {"sensor_enabled": True, "sensor_range_m": 240.0, "comm_range_m": 650.0},
        }
        for vid, vehicle in fleet.items():
            base = defaults.get(vehicle.kind, defaults["quadrotor"])
            self.settings.setdefault(vid, deepcopy(base))
        for vid in list(self.settings):
            if vid not in fleet:
                self.settings.pop(vid, None)

    def configure_vehicle(self, vehicle_id: str, patch: dict, fleet):
        self.ensure_fleet(fleet)
        if vehicle_id not in fleet:
            raise KeyError(vehicle_id)
        allowed = {"sensor_enabled", "sensor_range_m", "comm_range_m"}
        if set(patch) - allowed:
            raise ValueError("Unsupported sensor configuration field")
        current = self.settings[vehicle_id]
        updated = {**current, **patch}
        if not isinstance(updated["sensor_enabled"], bool):
            raise ValueError("sensor_enabled must be a boolean")
        for field, low, high in (("sensor_range_m", 50, 1000), ("comm_range_m", 100, 2000)):
            value = updated[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
                raise ValueError(f"{field} must be between {low} and {high} metres")
            updated[field] = round(float(value), 1)
        self.settings[vehicle_id] = updated
        self.record_event("SENSOR_CONFIG_UPDATED", vehicle_id, updated)
        return deepcopy(updated)

    def create_object(self, x: float, y: float, label: str, category: str,
                      difficulty: str, visible: bool = True) -> dict:
        if len([o for o in self.objects if not o.get("deleted")]) >= MAX_OBJECTS:
            raise ValueError(f"At most {MAX_OBJECTS} active test objects are allowed")
        self._validate_object(x, y, label, category, difficulty, visible)
        item = {
            "object_id": str(uuid4())[:10], "x": round(float(x), 3), "y": round(float(y), 3),
            "label": label.strip(), "category": category, "difficulty": difficulty,
            "visible": visible, "revision": 1, "created_at": now_iso(), "updated_at": now_iso(),
            "deleted": False,
        }
        self.objects.insert(0, item)
        self.record_event("TEST_OBJECT_CREATED", None, {k: item[k] for k in ("object_id", "x", "y", "label", "category", "difficulty", "visible")})
        return deepcopy(item)

    @staticmethod
    def _validate_object(x, y, label, category, difficulty, visible):
        if isinstance(x, bool) or isinstance(y, bool) or not (0 <= float(x) <= 100 and 0 <= float(y) <= 100):
            raise ValueError("Object coordinates must be within the 0–100 simulation map")
        if not in_geofence(float(x), float(y)):
            raise ValueError("Test object must be inside the operating geofence")
        if in_no_go_zone(float(x), float(y)):
            raise ValueError("Test object cannot be placed inside a restricted no-go zone")
        if not isinstance(label, str) or not 2 <= len(label.strip()) <= 100:
            raise ValueError("Object label must contain 2–100 characters")
        if category not in CATEGORY_ALLOWLIST:
            raise ValueError("Unsupported object category")
        if difficulty not in DIFFICULTY_FACTOR:
            raise ValueError("Difficulty must be easy, medium or hard")
        if not isinstance(visible, bool):
            raise ValueError("visible must be a boolean")

    def update_object(self, object_id: str, patch: dict) -> dict:
        item = next((o for o in self.objects if o["object_id"] == object_id and not o.get("deleted")), None)
        if not item:
            raise KeyError(object_id)
        candidate = {**item, **patch}
        self._validate_object(candidate["x"], candidate["y"], candidate["label"],
                              candidate["category"], candidate["difficulty"], candidate["visible"])
        changed = any(candidate.get(k) != item.get(k) for k in ("x", "y", "label", "category", "difficulty", "visible"))
        if changed:
            for key in ("x", "y", "label", "category", "difficulty", "visible"):
                item[key] = candidate[key]
            item["revision"] += 1
            item["updated_at"] = now_iso()
            self.record_event("TEST_OBJECT_UPDATED", None, {"object_id": object_id, "revision": item["revision"], **patch})
        return deepcopy(item)

    def delete_object(self, object_id: str) -> dict:
        item = next((o for o in self.objects if o["object_id"] == object_id and not o.get("deleted")), None)
        if not item:
            raise KeyError(object_id)
        item["deleted"] = True
        item["deleted_at"] = now_iso()
        self.record_event("TEST_OBJECT_REMOVED", None, {"object_id": object_id, "label": item["label"]})
        return {"object_id": object_id, "deleted": True}

    def _observation_key(self, obj: dict, vehicle_id: str) -> str:
        return f"{obj['object_id']}:{obj['revision']}:{vehicle_id}"

    def scan(self, fleet, swarm) -> list[dict]:
        """Create one deterministic local observation per vehicle/object revision."""
        self.ensure_fleet(fleet)
        swarm.update_link_geometry(fleet, self.settings)
        created = []
        metres_per_unit = THEATRE_WIDTH_M / 100.0
        for obj in self.objects:
            if obj.get("deleted") or not obj.get("visible", True):
                continue
            for vid, vehicle in fleet.items():
                settings = self.settings.get(vid, {})
                key = self._observation_key(obj, vid)
                if key in self._observed_keys or not settings.get("sensor_enabled", True):
                    continue
                if vehicle.failed or vehicle.status in ("failed", "landed") or vehicle.battery_pct <= 5:
                    continue
                distance_m = hypot(vehicle.x - obj["x"], vehicle.y - obj["y"]) * metres_per_unit
                effective_range = float(settings.get("sensor_range_m", 0)) * DIFFICULTY_FACTOR[obj["difficulty"]]
                if effective_range <= 0 or distance_m > effective_range:
                    continue
                proximity = max(0.0, 1.0 - distance_m / effective_range)
                difficulty_penalty = {"easy": 0.0, "medium": 0.035, "hard": 0.075}[obj["difficulty"]]
                confidence = round(min(0.99, max(0.5, 0.58 + 0.34 * proximity - difficulty_penalty)), 3)
                observation = {
                    "observation_id": str(uuid4())[:10], "object_id": obj["object_id"],
                    "object_revision": obj["revision"], "source_vehicle_id": vid,
                    "source_vehicle_name": vehicle.name, "label": obj["label"],
                    "category": obj["category"], "x": obj["x"], "y": obj["y"],
                    "distance_m": round(distance_m, 1), "confidence": confidence,
                    "difficulty": obj["difficulty"], "modality": "simulated_sensor_footprint",
                    "timestamp": now_iso(), "shared_status": "LOCAL_ONLY", "delivered_to": [],
                }
                message = swarm.publish(vid, "SENSOR_OBSERVATION", {
                    "observation_id": observation["observation_id"], "object_id": obj["object_id"],
                    "object_revision": obj["revision"], "label": obj["label"],
                    "category": obj["category"], "x": obj["x"], "y": obj["y"],
                    "confidence": confidence, "modality": "simulated_sensor_footprint",
                    "provenance": {"source_vehicle_id": vid, "source_vehicle_name": vehicle.name},
                })
                observation["delivered_to"] = list(message.get("delivered_to", []))
                observation["shared_status"] = "SHARED" if observation["delivered_to"] else "LOCAL_ONLY"
                self.observations.insert(0, observation)
                self._observed_keys.add(key)
                self.record_event("SENSOR_OBSERVATION", vid, observation)
                created.append(deepcopy(observation))
        del self.observations[MAX_OBSERVATIONS:]
        return created

    def capture_telemetry(self, fleet, swarm):
        self.ensure_fleet(fleet)
        self.tick_count += 1
        for vid, vehicle in fleet.items():
            settings = self.settings.get(vid, {})
            self.telemetry.append({
                "sample_id": str(uuid4())[:10], "tick": self.tick_count,
                "timestamp": now_iso(), "vehicle_id": vid, "vehicle_name": vehicle.name,
                "x": round(vehicle.x, 3), "y": round(vehicle.y, 3),
                "speed_mps": round(vehicle.speed, 3), "heading_deg": round(vehicle.heading_deg, 2),
                "altitude_m": round(vehicle.altitude_m, 2), "battery_pct": round(vehicle.battery_pct, 2),
                "status": vehicle.status, "failed": bool(vehicle.failed),
                "radio_enabled": bool(swarm.radios.get(vid, True)),
                "sensor_enabled": bool(settings.get("sensor_enabled", True)),
                "sensor_range_m": settings.get("sensor_range_m", 0),
                "comm_range_m": settings.get("comm_range_m", 0),
            })
        del self.telemetry[:-MAX_TELEMETRY]

    def record_event(self, event_type: str, vehicle_id: str | None, payload: dict):
        event = {"event_id": str(uuid4())[:10], "timestamp": now_iso(),
                 "event_type": event_type, "vehicle_id": vehicle_id,
                 "payload": deepcopy(payload)}
        self.events.insert(0, event)
        del self.events[MAX_EVENTS:]
        return event

    def state(self, fleet):
        self.ensure_fleet(fleet)
        active_objects = [deepcopy(o) for o in self.objects if not o.get("deleted")]
        vehicle_layers = []
        for vid, vehicle in fleet.items():
            setting = self.settings[vid]
            vehicle_layers.append({"vehicle_id": vid, "vehicle_name": vehicle.name,
                "x": round(vehicle.x, 3), "y": round(vehicle.y, 3),
                "sensor_enabled": setting["sensor_enabled"],
                "sensor_range_m": setting["sensor_range_m"],
                "comm_range_m": setting["comm_range_m"],
                "status": vehicle.status, "failed": vehicle.failed})
        overlap_pairs = []
        metres_per_unit = THEATRE_WIDTH_M / 100.0
        for i, first in enumerate(vehicle_layers):
            for second in vehicle_layers[i+1:]:
                if not first["sensor_enabled"] or not second["sensor_enabled"]:
                    continue
                distance = hypot(first["x"]-second["x"], first["y"]-second["y"]) * metres_per_unit
                if distance <= first["sensor_range_m"] + second["sensor_range_m"]:
                    overlap_pairs.append({"vehicles": [first["vehicle_id"], second["vehicle_id"]],
                                          "centre_distance_m": round(distance, 1)})
        object_summaries = []
        for obj in active_objects:
            records = [o for o in self.observations if o["object_id"] == obj["object_id"] and o["object_revision"] == obj["revision"]]
            sources = sorted({o["source_vehicle_id"] for o in records})
            object_summaries.append({**obj, "observation_count": len(records), "observed_by": sources,
                "information_status": "CORROBORATED" if len(sources) >= 2 else "SINGLE_SOURCE" if sources else "UNOBSERVED"})
        return {"settings": deepcopy(self.settings), "vehicles": vehicle_layers,
                "objects": object_summaries, "observations": deepcopy(self.observations[:200]),
                "overlap_pairs": overlap_pairs,
                "summary": {"active_objects": len(active_objects), "observations": len(self.observations),
                            "corroborated_objects": sum(1 for x in object_summaries if x["information_status"] == "CORROBORATED"),
                            "sensor_enabled": sum(1 for x in vehicle_layers if x["sensor_enabled"])}}

    def blackbox(self, vehicle_id: str | None = None, limit: int = 180):
        rows = [r for r in self.telemetry if vehicle_id is None or r["vehicle_id"] == vehicle_id]
        return {"vehicle_id": vehicle_id, "samples": deepcopy(rows[-limit:]),
                "events": deepcopy([e for e in self.events if vehicle_id is None or e["vehicle_id"] in (None, vehicle_id)][:200]),
                "sample_count": len(rows), "tick_count": self.tick_count}

    def snapshot(self):
        return {"settings": deepcopy(self.settings), "objects": deepcopy(self.objects),
                "observations": deepcopy(self.observations[-MAX_OBSERVATIONS:]),
                "telemetry": deepcopy(self.telemetry[-MAX_TELEMETRY:]),
                "events": deepcopy(self.events[:MAX_EVENTS]), "tick_count": self.tick_count,
                "observed_keys": sorted(self._observed_keys)[-MAX_OBSERVATIONS:],
                "automated_keys": sorted(self._automated_keys)[-MAX_OBJECTS:],
                "automation_retry_after": deepcopy(self._automation_retry_after),
                "automation": deepcopy(self.automation)}

    def restore(self, payload: dict | None, fleet):
        self.ensure_fleet(fleet)
        if not isinstance(payload, dict):
            return
        settings = payload.get("settings", {})
        if isinstance(settings, dict):
            for vid in fleet:
                entry = settings.get(vid)
                if isinstance(entry, dict):
                    try:
                        self.configure_vehicle(vid, entry, fleet)
                    except ValueError:
                        continue
        self.objects = [x for x in payload.get("objects", []) if isinstance(x, dict)][-MAX_OBJECTS:]
        self.observations = [x for x in payload.get("observations", []) if isinstance(x, dict)][:MAX_OBSERVATIONS]
        self.telemetry = [x for x in payload.get("telemetry", []) if isinstance(x, dict)][-MAX_TELEMETRY:]
        self.events = [x for x in payload.get("events", []) if isinstance(x, dict)][:MAX_EVENTS]
        self.tick_count = max(0, int(payload.get("tick_count", 0)))
        keys = payload.get("observed_keys", [])
        self._observed_keys = {str(x) for x in keys if isinstance(x, str)}
        self._automated_keys = {str(x) for x in payload.get("automated_keys", []) if isinstance(x, str)}
        retry = payload.get("automation_retry_after", {})
        self._automation_retry_after = {str(k): int(v) for k,v in retry.items() if isinstance(v, int)} if isinstance(retry, dict) else {}
        automation = payload.get("automation", {})
        if isinstance(automation, dict):
            enabled = automation.get("enabled", True)
            confidence = automation.get("min_confidence", 0.65)
            sources = automation.get("min_sources", 2)
            if isinstance(enabled, bool) and isinstance(confidence, (int, float)) and 0 <= confidence <= 1 and isinstance(sources, int) and 1 <= sources <= 3:
                self.automation = {"enabled": enabled, "min_confidence": float(confidence), "min_sources": sources}
        # Rebuild keys from observation history for compatibility with older snapshots.
        for obs in self.observations:
            self._observed_keys.add(f"{obs.get('object_id')}:{obs.get('object_revision')}:{obs.get('source_vehicle_id')}")
