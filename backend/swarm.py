"""Deterministic in-process swarm message bus for the OmniFleet simulator.

This is a software simulation of structured vehicle-to-vehicle and
vehicle-to-coordinator messaging. It is not a radio, mesh network, MQTT broker,
ROS 2 DDS implementation, or hardware communication adapter.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from math import hypot
from uuid import uuid4
from .geospatial import THEATRE_WIDTH_M

MESSAGE_TYPES = {
    "HEARTBEAT", "POSITION_UPDATE", "BATTERY_UPDATE", "AVAILABILITY_UPDATE",
    "INTENT_BROADCAST", "TASK_REQUEST", "TASK_OFFER", "DETECTION_EVENT",
    "ROUTE_CONFLICT", "EMERGENCY_ALERT", "ACKNOWLEDGEMENT", "STATUS_REQUEST",
    "STATUS_REPORT", "OPERATOR_ANNOUNCEMENT", "PEER_TEST", "SENSOR_OBSERVATION",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SwarmNetwork:
    def __init__(self):
        self.config = {
            "enabled": True,
            "coordination_mode": "hybrid",  # centralized | hybrid
            "peer_mesh_enabled": True,
            "coordinator_link_enabled": True,
            "network_latency_ticks": 0,
            "packet_loss_pct": 0.0,
        }
        self.radios: dict[str, bool] = {}
        self.comm_ranges: dict[str, float] = {}
        self.positions: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.knowledge: dict = {"vehicles": {}, "by_recipient": {}, "detections": [], "route_conflicts": []}
        self.pending_delivery: list[dict] = []
        self.pending_coordination: dict[str, dict] = {}
        self.message_counter = 0
        self.tick_count = 0

    def ensure_fleet(self, fleet):
        for vid in fleet:
            self.radios.setdefault(vid, True)
            self.knowledge["vehicles"].setdefault(vid, {})
            self.knowledge["by_recipient"].setdefault(vid, {})
        for vid in list(self.radios):
            if vid not in fleet:
                self.radios.pop(vid, None)
                self.knowledge["vehicles"].pop(vid, None)
                self.knowledge["by_recipient"].pop(vid, None)
                for table in self.knowledge["by_recipient"].values(): table.pop(vid, None)
                self.positions.pop(vid, None)

    def update_link_geometry(self, fleet, sensor_settings):
        """Refresh simulated positions and nominal radio ranges before routing."""
        self.ensure_fleet(fleet)
        for vid, vehicle in fleet.items():
            self.positions[vid] = {"x": float(vehicle.x), "y": float(vehicle.y)}
            self.comm_ranges[vid] = float(sensor_settings.get(vid, {}).get("comm_range_m", 0))

    def _within_peer_range(self, sender: str, target: str) -> bool:
        a = self.positions.get(sender, {})
        b = self.positions.get(target, {})
        if not all(k in a and k in b for k in ("x", "y")):
            return False
        # Conservative symmetric link: both endpoints must fit within the shorter nominal range.
        radius = min(self.comm_ranges.get(sender, 0), self.comm_ranges.get(target, 0))
        return hypot(a["x"] - b["x"], a["y"] - b["y"]) * (THEATRE_WIDTH_M / 100.0) <= radius

    def configure(self, patch: dict, fleet):
        allowed = set(self.config)
        if set(patch) - allowed:
            raise ValueError("Unsupported swarm configuration field")
        if "coordination_mode" in patch and patch["coordination_mode"] not in ("centralized", "hybrid"):
            raise ValueError("coordination_mode must be 'centralized' or 'hybrid'")
        for key, value in patch.items():
            if key == "coordination_mode":
                continue
            if key in ("network_latency_ticks",) and (not isinstance(value,int) or isinstance(value,bool) or not 0 <= value <= 10):
                raise ValueError("network_latency_ticks must be an integer from 0 to 10")
            if key == "packet_loss_pct" and (not isinstance(value,(int,float)) or isinstance(value,bool) or not 0 <= float(value) <= 100):
                raise ValueError("packet_loss_pct must be between 0 and 100")
            if key in ("enabled", "peer_mesh_enabled", "coordinator_link_enabled") and not isinstance(value,bool):
                raise ValueError(f"{key} must be a boolean")
        self.config.update(patch)
        self.ensure_fleet(fleet)
        return self.public_state(fleet)

    def set_radio(self, vehicle_id: str, enabled: bool, fleet):
        self.ensure_fleet(fleet)
        if vehicle_id not in fleet:
            raise KeyError(vehicle_id)
        if not isinstance(enabled, bool):
            raise ValueError("radio enabled must be a boolean")
        self.radios[vehicle_id] = enabled
        if enabled:
            self.publish("coordinator", "AVAILABILITY_UPDATE", {"vehicle_id": vehicle_id, "radio": "online"}, [vehicle_id])
        else:
            self._record("coordinator", "AVAILABILITY_UPDATE", {"vehicle_id": vehicle_id, "radio": "offline"}, [], "BLOCKED", "control")
        return self.public_state(fleet)

    def _record(self, sender, message_type, payload, delivered_to, status, channel, recipients=None,
                queued_to=None, dropped_to=None):
        message = {
            "id": str(uuid4())[:10], "timestamp": now_iso(), "sender": sender,
            "recipients": list(recipients or []), "delivered_to": list(delivered_to),
            "queued_to": list(queued_to or []), "dropped_to": list(dropped_to or []),
            "message_type": message_type, "payload": deepcopy(payload),
            "status": status, "channel": channel,
        }
        self.messages.append(message)
        del self.messages[:-400]
        return message

    def _deterministic_packet_drop(self, sender, target):
        import zlib
        self.message_counter += 1
        token=f"{self.tick_count}:{self.message_counter}:{sender}:{target}".encode()
        return (zlib.crc32(token) % 10000) < int(float(self.config.get("packet_loss_pct",0))*100)

    def _remember_vehicle_state(self, sender, recipient, payload):
        record={"vehicle_id":sender, **deepcopy(payload), "radio_enabled":True,
                "last_seen":now_iso(), "observed_by":recipient}
        if recipient == "coordinator":
            self.knowledge["vehicles"][sender]=record
        elif recipient in self.radios:
            self.knowledge["by_recipient"].setdefault(recipient,{})[sender]=record

    def publish(self, sender: str, message_type: str, payload: dict,
                recipients: list[str] | None = None, channel: str = "fleet") -> dict:
        if message_type not in MESSAGE_TYPES:
            raise ValueError("Message type is not part of the allowlisted swarm protocol")
        if not isinstance(payload, dict):
            raise ValueError("Message payload must be a JSON object")
        if not self.config["enabled"]:
            return self._record(sender, message_type, payload, [], "BLOCKED_NETWORK_DISABLED", channel, recipients)
        vehicle_sender = sender not in ("operator", "coordinator")
        if vehicle_sender and not self.radios.get(sender, False):
            return self._record(sender, message_type, payload, [], "BLOCKED_SENDER_RADIO_OFF", channel, recipients)

        targets = ([vid for vid, enabled in self.radios.items() if enabled and vid != sender]
                   if recipients is None else list(dict.fromkeys(recipients)))
        reachable=[]; blocked=[]
        for target in targets:
            if target in ("operator", "coordinator"):
                (reachable if self.config["coordinator_link_enabled"] else blocked).append(target)
                continue
            if target not in self.radios or not self.radios[target]:
                blocked.append(target); continue
            peer_to_peer = vehicle_sender and target not in ("coordinator", "operator")
            direct_peer = (self.config["coordination_mode"] == "hybrid" and self.config["peer_mesh_enabled"] and peer_to_peer)
            if direct_peer:
                (reachable if self._within_peer_range(sender, target) else blocked).append(target)
            elif self.config["coordinator_link_enabled"]:
                reachable.append(target)
            else:
                blocked.append(target)

        if sender in ("operator","coordinator") and not self.config["coordinator_link_enabled"]:
            reachable=[]
        delivered=[]; queued=[]; dropped=list(blocked)
        latency=int(self.config.get("network_latency_ticks",0))
        for target in reachable:
            if self._deterministic_packet_drop(sender,target):
                dropped.append(target); continue
            if latency:
                queued.append(target)
            else:
                delivered.append(target)

        status = ("DELIVERED" if delivered and not dropped and not queued else
                  "PARTIAL" if delivered else "QUEUED" if queued else
                  "BLOCKED_PACKET_LOSS" if reachable and len(dropped)>=len(reachable) else "BLOCKED_NO_ROUTE")
        channel_name=("peer-mesh" if vehicle_sender and self.config["coordination_mode"]=="hybrid" and self.config["peer_mesh_enabled"] else "coordinator-relay")
        message=self._record(sender,message_type,payload,delivered,status,channel_name,targets,queued,dropped)
        for recipient in delivered:
            if message_type == "HEARTBEAT": self._remember_vehicle_state(sender,recipient,payload)
        for recipient in queued:
            self.pending_delivery.append({"message_id":message["id"],"sender":sender,"recipient":recipient,
                "message_type":message_type,"payload":deepcopy(payload),"remaining_ticks":latency,
                "direct_peer":vehicle_sender and recipient not in ("operator","coordinator")
                    and self.config["coordination_mode"]=="hybrid" and self.config["peer_mesh_enabled"]})
        return message

    def advance_network(self, fleet):
        """Advance queued deliveries by one simulation tick and apply link rechecks."""
        self.update_link_geometry(fleet,{vid:{"comm_range_m":self.comm_ranges.get(vid,0)} for vid in fleet})
        remaining=[]
        delivered_events=[]
        acknowledgements=[]
        for item in self.pending_delivery:
            item["remaining_ticks"]-=1
            if item["remaining_ticks"]>0:
                remaining.append(item); continue
            recipient=item["recipient"]; sender=item["sender"]
            link_ok=self.config["enabled"]
            if recipient in ("operator","coordinator"):
                link_ok=link_ok and self.config["coordinator_link_enabled"]
            else:
                link_ok=link_ok and self.radios.get(recipient,False)
                if item.get("direct_peer"):
                    link_ok=link_ok and self.radios.get(sender,False) and self._within_peer_range(sender,recipient)
            message=next((m for m in self.messages if m["id"]==item["message_id"]),None)
            if message is None: continue
            if link_ok:
                if recipient not in message["delivered_to"]: message["delivered_to"].append(recipient)
                if recipient in message["queued_to"]: message["queued_to"].remove(recipient)
                if item["message_type"]=="HEARTBEAT": self._remember_vehicle_state(sender,recipient,item["payload"])
                delivered_events.append({"message_id":message["id"],"sender":sender,"recipient":recipient,
                    "message_type":item["message_type"],"payload":deepcopy(item["payload"])})
                if item["message_type"] != "ACKNOWLEDGEMENT" and recipient in self.radios:
                    # Queue the ACK after this delivery pass, so a delayed ACK
                    # is not lost when the pending queue is replaced below.
                    acknowledgements.append((recipient,sender,message["id"],item["message_type"]))
            else:
                if recipient in message["queued_to"]: message["queued_to"].remove(recipient)
                message.setdefault("dropped_to",[]).append(recipient)
            if message["delivered_to"]:
                message["status"]="PARTIAL" if message["queued_to"] or message["dropped_to"] else "DELIVERED"
            elif message["queued_to"]:
                message["status"]="QUEUED"
            else:
                message["status"]="BLOCKED_LINK_LOST"
        self.pending_delivery=remaining
        for recipient,sender,message_id,message_type in acknowledgements:
            self.publish(recipient,"ACKNOWLEDGEMENT",{
                "acknowledged_message_id":message_id,
                "acknowledged_type":message_type,
                "status":"received"},[sender],channel="peer-mesh")
        return delivered_events

    def acknowledge(self, original: dict):
        if original["status"] not in ("DELIVERED", "PARTIAL"):
            return []
        sender = original["sender"]
        if sender in ("operator", "coordinator"):
            return []
        acknowledgements = []
        for recipient in original["delivered_to"]:
            if recipient not in self.radios:
                continue
            acknowledgements.append(self.publish(recipient, "ACKNOWLEDGEMENT", {
                "acknowledged_message_id": original["id"],
                "acknowledged_type": original["message_type"],
                "status": "received",
            }, [sender], channel="peer-mesh"))
        return acknowledgements

    def announce_intent(self, vehicle_id: str, action: dict):
        message = self.publish(vehicle_id, "INTENT_BROADCAST", {
            "vehicle_id": vehicle_id, "action": action.get("action"),
            "target": {k: action[k] for k in ("x", "y") if k in action},
            "route_waypoints": len(action.get("route_points", [])),
            "note": "Intent announcement only; execution remains governed by approved mission.",
        })
        self.acknowledge(message)
        return message

    def sync_fleet(self, fleet):
        """Exchange periodic state only over links that actually deliver."""
        self.ensure_fleet(fleet)
        self.tick_count += 1
        self.update_link_geometry(fleet, {vid: {"comm_range_m": self.comm_ranges.get(vid, 0)} for vid in fleet})
        deliveries=self.advance_network(fleet)
        if self.tick_count % 5 != 0:
            return deliveries
        for vid, vehicle in fleet.items():
            if not self.radios.get(vid, True) or not self.config["enabled"]:
                continue
            payload = {"status": vehicle.status, "battery_pct": round(vehicle.battery_pct, 2),
                       "x": round(vehicle.x, 3), "y": round(vehicle.y, 3),
                       "kind": vehicle.kind, "name": vehicle.name}
            heartbeat = self.publish(vid, "HEARTBEAT", payload, [*([x for x in self.radios if x != vid]), "coordinator"])
            self.publish(vid, "POSITION_UPDATE", {"x":payload["x"],"y":payload["y"]})
            self.publish(vid, "BATTERY_UPDATE", {"battery_pct":payload["battery_pct"]})
            self.publish(vid, "AVAILABILITY_UPDATE", {"status":vehicle.status,"available":vehicle.status in ("ready","holding") and not vehicle.failed})
            self.acknowledge(heartbeat)
        return deliveries

    def record_detection(self, vehicle_id: str, x: float, y: float, label: str, confidence: float):
        detection = {
            "detection_id": str(uuid4())[:10], "source_vehicle_id": vehicle_id,
            "x": round(float(x), 3), "y": round(float(y), 3),
            "label": label, "confidence": round(float(confidence), 3), "timestamp": now_iso(),
        }
        self.knowledge["detections"].insert(0, detection)
        del self.knowledge["detections"][50:]
        message = self.publish(vehicle_id, "DETECTION_EVENT", detection)
        self.acknowledge(message)
        return detection, message

    def public_state(self, fleet):
        self.ensure_fleet(fleet)
        online_radios = sum(1 for vid in fleet if self.radios.get(vid, True))
        return {
            "config": deepcopy(self.config),
            "radios": deepcopy(self.radios),
            "link_ranges_m": deepcopy(self.comm_ranges),
            "connectivity": {"vehicles_total": len(fleet), "radios_online": online_radios,
                             "coordinator_connected": bool(self.config["enabled"] and self.config["coordinator_link_enabled"]),
                             "peer_mesh_available": bool(self.config["enabled"] and self.config["coordination_mode"] == "hybrid" and self.config["peer_mesh_enabled"]),
                             "network_status": "ONLINE" if self.config["enabled"] else "PAUSED"},
            "messages": list(reversed(self.messages[-100:])),
            "pending_deliveries":len(self.pending_delivery),
            "pending_coordination":len(self.pending_coordination),
            "network_simulation":{"latency_ticks":self.config.get("network_latency_ticks",0),
                                   "packet_loss_pct":self.config.get("packet_loss_pct",0)},
            "knowledge": deepcopy(self.knowledge),
        }

    def snapshot(self):
        return {"config": deepcopy(self.config), "radios": deepcopy(self.radios),
                "messages": deepcopy(self.messages[-400:]), "knowledge": deepcopy(self.knowledge),
                "comm_ranges": deepcopy(self.comm_ranges),
                "tick_count": self.tick_count, "pending_delivery":deepcopy(self.pending_delivery),
                "pending_coordination":deepcopy(self.pending_coordination),
                "message_counter":self.message_counter}

    def restore(self, payload: dict | None, fleet):
        self.ensure_fleet(fleet)
        if not payload:
            return
        config = payload.get("config", {})
        if isinstance(config, dict):
            self.configure(config, fleet)
        radios = payload.get("radios", {})
        for vid in fleet:
            if vid in radios and isinstance(radios[vid], bool):
                self.radios[vid] = radios[vid]
        messages = payload.get("messages", [])
        self.messages = [m for m in messages if isinstance(m, dict)][-400:]
        knowledge = payload.get("knowledge", {})
        if isinstance(knowledge, dict):
            self.knowledge.update({k: deepcopy(v) for k, v in knowledge.items() if k in ("vehicles", "by_recipient", "detections", "route_conflicts")})
        ranges = payload.get("comm_ranges", {})
        if isinstance(ranges, dict):
            self.comm_ranges.update({k: float(v) for k, v in ranges.items() if k in fleet and isinstance(v, (int, float))})
        by_recipient=knowledge.get("by_recipient", {}) if isinstance(knowledge,dict) else {}
        if isinstance(by_recipient,dict): self.knowledge["by_recipient"].update({k:deepcopy(v) for k,v in by_recipient.items() if k in fleet and isinstance(v,dict)})
        self.pending_delivery=[x for x in payload.get("pending_delivery",[]) if isinstance(x,dict)][-1000:]
        pending=payload.get("pending_coordination",{})
        self.pending_coordination={str(k):deepcopy(v) for k,v in pending.items() if isinstance(v,dict)} if isinstance(pending,dict) else {}
        self.message_counter=int(payload.get("message_counter",0))
        self.tick_count = int(payload.get("tick_count", 0))
