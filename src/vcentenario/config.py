import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple


@dataclass(frozen=True)
class BridgeArea:
    name: str
    road: str
    km_min: float
    km_max: float
    bbox: Tuple[float, float, float, float]
    panel_location_ids: Tuple[str, ...] = field(default_factory=tuple)
    preferred_camera_ids: Tuple[str, ...] = field(default_factory=tuple)
    preferred_detector_ids: Tuple[str, ...] = field(default_factory=tuple)


ROOT_DIR = Path(__file__).resolve().parents[2]
VAR_DIR = ROOT_DIR / "var"


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    return Path(raw).expanduser()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_DB_PATH = _env_path("VCENTENARIO_DB_PATH", VAR_DIR / "vcentenario.db")
DEFAULT_SNAPSHOTS_DIR = _env_path("VCENTENARIO_SNAPSHOTS_DIR", VAR_DIR / "snapshots")
REQUEST_TIMEOUT = _env_int("VCENTENARIO_REQUEST_TIMEOUT", 30)
HTTP_MAX_RETRIES = _env_int("VCENTENARIO_HTTP_MAX_RETRIES", 2)
HTTP_RETRY_BACKOFF_SECONDS = _env_float("VCENTENARIO_HTTP_RETRY_BACKOFF_SECONDS", 1.5)
USER_AGENT = os.getenv("VCENTENARIO_USER_AGENT", "VCentenario/0.2 (+https://nap.dgt.es)")
ENABLE_REFRESH_ENDPOINT = _env_bool("VCENTENARIO_ENABLE_REFRESH_ENDPOINT", False)
REFRESH_TOKEN = os.getenv("VCENTENARIO_REFRESH_TOKEN", "").strip()
REFRESH_MIN_INTERVAL_SECONDS = _env_int("VCENTENARIO_REFRESH_MIN_INTERVAL_SECONDS", 120)
REVERSIBLE_PERSISTENCE_WINDOW = _env_int("VCENTENARIO_REVERSIBLE_PERSISTENCE_WINDOW", 8)
REVERSIBLE_SCHEDULE = os.getenv(
    "VCENTENARIO_REVERSIBLE_SCHEDULE",
    "mon-fri@06:00-12:30=negative;mon-fri@15:00-21:00=positive",
)
KEEP_STATES = _env_int("VCENTENARIO_KEEP_STATES", 500)
KEEP_COLLECTION_RUNS = _env_int("VCENTENARIO_KEEP_COLLECTION_RUNS", 500)
KEEP_BATCHES = _env_int("VCENTENARIO_KEEP_BATCHES", 240)
KEEP_SNAPSHOTS_PER_CAMERA = _env_int("VCENTENARIO_KEEP_SNAPSHOTS_PER_CAMERA", 72)
ENABLE_VISION = _env_bool("VCENTENARIO_ENABLE_VISION", True)
YOLO_MODEL_PATH = _env_path("VCENTENARIO_YOLO_MODEL_PATH", ROOT_DIR / "yolov8n.pt")

BRIDGE_AREA = BridgeArea(
    name="Puente del Centenario",
    road="SE-30",
    km_min=13.0,
    km_max=15.0,
    bbox=(37.36, 37.38, -6.03, -6.00),
    panel_location_ids=("GUID_PMV_60621", "GUID_PMV_60859", "GUID_PMV_166911"),
    preferred_camera_ids=("1337", "167841"),
    preferred_detector_ids=(
        "GUID_DET_132943",
        "GUID_DET_132946",
        "GUID_DET_133803",
        "GUID_DET_133805",
        "GUID_DET_133806",
        "GUID_DET_133801",
        "GUID_DET_132918",
        "GUID_DET_132914",
    ),
)

DETECTORS_URL = "https://infocar.dgt.es/datex2/dgt/MeasuredDataPublication/detectores/content.xml"
DETECTORS_INVENTORY_URL = "https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/detectores/content.xml"
PANELS_URL = "https://infocar.dgt.es/datex2/dgt/SituationPublication/paneles/content.xml"
PANELS_INVENTORY_URL = "https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/paneles/content.xml"
INCIDENTS_URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml"
CAMERAS_URL = "https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml"

DETECTORS_NS_V1 = {"d": "http://datex2.eu/schema/1_0/1_0"}
PANELS_NS_V1 = {"d": "http://datex2.eu/schema/1_0/1_0"}
COMMON_NS_V3 = {
    "com": "http://levelC/schema/3/common",
    "d2": "http://levelC/schema/3/d2Payload",
    "fse": "http://levelC/schema/3/faultAndStatusSpanishExtension",
    "loc": "http://levelC/schema/3/locationReferencing",
    "lse": "http://levelC/schema/3/locationReferencingSpanishExtension",
    "ns2": "http://levelC/schema/3/faultAndStatus",
    "sit": "http://levelC/schema/3/situation",
}
