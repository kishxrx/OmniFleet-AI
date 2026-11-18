from typing import Literal
from pydantic import BaseModel, Field
ActionName = Literal["goto", "hold", "return_home", "land"]
class PlanRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=1200)


class MapWaypointRequest(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class CoveragePoint(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)

class CoveragePlanRequest(BaseModel):
    polygon: list[CoveragePoint] = Field(min_length=3, max_length=40)
    lane_spacing_m: float = Field(default=80, ge=20, le=300)

class SwarmConfigRequest(BaseModel):
    enabled: bool | None = None
    coordination_mode: Literal["centralized", "hybrid"] | None = None
    peer_mesh_enabled: bool | None = None
    coordinator_link_enabled: bool | None = None
    network_latency_ticks: int | None = Field(default=None, ge=0, le=10)
    packet_loss_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)

class VehicleRadioRequest(BaseModel):
    enabled: bool

class SwarmBroadcastRequest(BaseModel):
    message: str = Field(min_length=2, max_length=500)
    recipients: list[str] | None = Field(default=None, max_length=10)

class DetectionEventRequest(BaseModel):
    source_vehicle_id: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0, le=100, allow_inf_nan=False)
    y: float = Field(ge=0, le=100, allow_inf_nan=False)
    label: str = Field(default="Unclassified anomaly", min_length=2, max_length=100)
    confidence: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)

class PeerTestRequest(BaseModel):
    sender_vehicle_id: str = Field(min_length=1, max_length=80)
    recipient_vehicle_id: str = Field(min_length=1, max_length=80)
    message: str = Field(default="Peer-to-peer link test", min_length=2, max_length=200)


class TestObjectCreateRequest(BaseModel):
    x: float = Field(ge=0, le=100, allow_inf_nan=False)
    y: float = Field(ge=0, le=100, allow_inf_nan=False)
    label: str = Field(min_length=2, max_length=100)
    category: Literal["marker", "vehicle", "person", "structure", "other"] = "marker"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    visible: bool = True

class TestObjectUpdateRequest(BaseModel):
    x: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    label: str | None = Field(default=None, min_length=2, max_length=100)
    category: Literal["marker", "vehicle", "person", "structure", "other"] | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    visible: bool | None = None

class SensorVehicleConfigRequest(BaseModel):
    sensor_enabled: bool | None = None
    sensor_range_m: float | None = Field(default=None, ge=50, le=1000, allow_inf_nan=False)
    comm_range_m: float | None = Field(default=None, ge=100, le=2000, allow_inf_nan=False)


class SensorAutomationRequest(BaseModel):
    enabled: bool | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    min_sources: int | None = Field(default=None, ge=1, le=3)
