import os
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Dict, Tuple

# Carga automática de .env (sin dependencias externas)
_env_file = Path(__file__).resolve().parents[2] / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


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
LOCAL_TIMEZONE = os.getenv("VCENTENARIO_LOCAL_TIMEZONE", "Europe/Madrid")
ENABLE_REFRESH_ENDPOINT = _env_bool("VCENTENARIO_ENABLE_REFRESH_ENDPOINT", False)
REFRESH_TOKEN = os.getenv("VCENTENARIO_REFRESH_TOKEN", "").strip()
REFRESH_MIN_INTERVAL_SECONDS = _env_int("VCENTENARIO_REFRESH_MIN_INTERVAL_SECONDS", 120)
REVERSIBLE_PERSISTENCE_WINDOW = _env_int("VCENTENARIO_REVERSIBLE_PERSISTENCE_WINDOW", 8)
REVERSIBLE_SCHEDULE = os.getenv(
    "VCENTENARIO_REVERSIBLE_SCHEDULE",
    "mon-fri@06:00-12:30=negative;mon-fri@15:00-21:00=positive",
)
DETECTOR_MAX_AGE_MINUTES = _env_int("VCENTENARIO_DETECTOR_MAX_AGE_MINUTES", 30)
PROFILE_EMA_ALPHA = _env_float("VCENTENARIO_PROFILE_EMA_ALPHA", 0.18)
KEEP_STATES = _env_int("VCENTENARIO_KEEP_STATES", 500)
KEEP_COLLECTION_RUNS = _env_int("VCENTENARIO_KEEP_COLLECTION_RUNS", 500)
KEEP_BATCHES = _env_int("VCENTENARIO_KEEP_BATCHES", 240)
KEEP_SNAPSHOTS_PER_CAMERA = _env_int("VCENTENARIO_KEEP_SNAPSHOTS_PER_CAMERA", 72)
ENABLE_VISION = _env_bool("VCENTENARIO_ENABLE_VISION", True)
YOLO_MODEL_PATH = _env_path("VCENTENARIO_YOLO_MODEL_PATH", ROOT_DIR / "yolov8m.pt")
YOLO_CONFIDENCE = _env_float("VCENTENARIO_YOLO_CONFIDENCE", 0.1)
YOLO_IMAGE_SIZE = _env_int("VCENTENARIO_YOLO_IMAGE_SIZE", 1280)
YOLO_ENABLE_TILING = _env_bool("VCENTENARIO_YOLO_ENABLE_TILING", True)
YOLO_TILE_OVERLAP = _env_float("VCENTENARIO_YOLO_TILE_OVERLAP", 0.2)
DETECTOR_MAX_AGE = timedelta(minutes=max(1, DETECTOR_MAX_AGE_MINUTES))
TOMTOM_API_KEY = os.getenv("VCENTENARIO_TOMTOM_API_KEY", "").strip()
ADSENSE_CLIENT_ID = os.getenv("VCENTENARIO_ADSENSE_CLIENT_ID", "").strip()
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
TOMTOM_INCIDENTS_URL = "https://api.tomtom.com/traffic/services/4/incidentDetails/s3/{bbox}/10/-1/json"
TOMTOM_SPEED_CAMERAS_URL = "https://api.tomtom.com/traffic/services/4/speedLimitInfo/s3/{bbox}/10/-1/json"
TOMTOM_CALIBRATED_FREE_FLOW = 60.0
# Offset estructural direccional: Huelva(+) es ~4 km/h más rápido que Cádiz(−)
# en TomTom Routing incluso con tráfico muerto. Se resta a Huelva antes de
# calcular asimetría direccional en la inferencia del reversible.
TOMTOM_DIRECTION_BASELINE_OFFSET = _env_float("VCENTENARIO_TOMTOM_DIRECTION_BASELINE_OFFSET", 4.0)

# Alert settings
ALERT_EMAIL_ENABLED = _env_bool("VCENTENARIO_ALERT_EMAIL_ENABLED", False)
ALERT_EMAIL_SMTP_SERVER = os.getenv("VCENTENARIO_ALERT_EMAIL_SMTP_SERVER", "smtp.gmail.com")
ALERT_EMAIL_SMTP_PORT = _env_int("VCENTENARIO_ALERT_EMAIL_SMTP_PORT", 587)
ALERT_EMAIL_USER = os.getenv("VCENTENARIO_ALERT_EMAIL_USER", "")
ALERT_EMAIL_PASSWORD = os.getenv("VCENTENARIO_ALERT_EMAIL_PASSWORD", "")
ALERT_EMAIL_RECIPIENTS = os.getenv("VCENTENARIO_ALERT_EMAIL_RECIPIENTS", "").split(",") if os.getenv("VCENTENARIO_ALERT_EMAIL_RECIPIENTS") else []
ALERT_TRAFFIC_SCORE_THRESHOLD = _env_float("VCENTENARIO_ALERT_TRAFFIC_SCORE_THRESHOLD", 50.0)
ALERT_INCIDENT_SEVERITY_THRESHOLD = os.getenv("VCENTENARIO_ALERT_INCIDENT_SEVERITY_THRESHOLD", "high")

BRIDGE_AREA = BridgeArea(
    name="SE-30 km 10–12 · Sentido Huelva",
    road="SE-30",
    # Tramo de interés: km 10–12, sentido Huelva (positivo, km creciente).
    # km 10: (37.343820, -5.986923) · km 12: (37.357216, -6.002909)
    # bbox cubre lat 37.338–37.362, lon -6.010–-5.980
    km_min=10.0,
    km_max=12.0,
    bbox=(37.338, 37.362, -6.010, -5.980),
    panel_location_ids=(
        # km 10.0
        "60514", "GUID_PMV_60514",
        # km 10.3
        "60833", "GUID_PMV_60833",
        # km 12.4 (límite del tramo)
        "60516", "GUID_PMV_60516",
    ),
    preferred_camera_ids=(),  # Sin cámaras conocidas en km 10-12 sentido Huelva
    preferred_detector_ids=(
        # km 10.0
        "GUID_DET_132877", "GUID_DET_132880", "GUID_DET_132875",
        # km 12.0
        "GUID_DET_139931", "GUID_DET_139930", "GUID_DET_139929",
        "GUID_DET_132386", "GUID_DET_132378", "GUID_DET_132374", "GUID_DET_132382",
        # km 12.1
        "GUID_DET_132411", "GUID_DET_132407", "GUID_DET_132394", "GUID_DET_132401",
    ),
)

# Dirección del tramo monitorizado: "positivo" = km creciente = sentido Huelva
SEGMENT_DIRECTION = "positivo"

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

CAMERA_DIRECTION_SPLITS: Dict[str, Dict[str, object]] = {
    "1337": {
        "axis": "x",
        "split": 320.0,
        "low_label": "descendente",
        "high_label": "ascendente",
        "zones": [
            {
                "label": "descendente",
                "polygon": [(0.0, 480.0), (0.0, 210.0), (150.0, 150.0), (345.0, 218.0), (268.0, 480.0)],
            },
            {
                "label": "ascendente",
                "polygon": [(238.0, 480.0), (348.0, 218.0), (470.0, 180.0), (545.0, 210.0), (530.0, 480.0)],
            },
        ],
    }
}
