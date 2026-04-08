from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PanelLocation:
    location_id: str
    name: str
    road: str
    km: Optional[float]
    direction: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]


@dataclass
class PanelMessage:
    situation_id: str
    record_id: str
    location_id: str
    road: Optional[str]
    km: Optional[float]
    direction: Optional[str]
    pictograms: List[str]
    legends: List[str]
    status: Optional[str]
    created_at: Optional[str]


@dataclass
class Incident:
    situation_id: str
    record_id: str
    road: Optional[str]
    direction: Optional[str]
    severity: Optional[str]
    validity_status: Optional[str]
    start_time: Optional[str]
    end_time: Optional[str]
    incident_type: Optional[str]
    cause_type: Optional[str]
    from_km: Optional[float]
    to_km: Optional[float]
    latitude: Optional[float]
    longitude: Optional[float]
    municipality: Optional[str]
    province: Optional[str]
    source: str = "dgt"
    magnitude: Optional[int] = None
    delay_seconds: Optional[int] = None
    length_meters: Optional[int] = None


@dataclass
class Camera:
    camera_id: str
    road: Optional[str]
    km: Optional[float]
    direction: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    image_url: str


@dataclass
class DetectorLocation:
    detector_id: str
    road: Optional[str]
    km: Optional[float]
    direction: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]


@dataclass
class DetectorReading:
    detector_id: str
    measured_at: Optional[str]
    road: Optional[str]
    km: Optional[float]
    direction: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    average_speed: Optional[float]
    vehicle_flow: Optional[int]
    occupancy: Optional[float]
    source: str = "dgt"
    free_flow_speed: Optional[float] = None


@dataclass
class CameraSnapshot:
    camera_id: str
    fetched_at: str
    http_status: int
    content_length: int
    sha256: Optional[str]
    image_path: Optional[str]
    last_modified: Optional[str]
    visual_change_score: Optional[float]
    vehicle_count: Optional[int] = None
    vehicle_counts_by_direction: Dict[str, int] = field(default_factory=dict)


@dataclass
class BridgeState:
    generated_at: str
    traffic_score: float
    traffic_level: str
    reversible_probable: str
    confidence: float
    official: bool = False
    evidence: List[str] = field(default_factory=list)
    breakdown: Dict[str, float] = field(default_factory=dict)
    forecast: Dict[str, object] = field(default_factory=dict)
    learning_context: Dict[str, object] = field(default_factory=dict)
