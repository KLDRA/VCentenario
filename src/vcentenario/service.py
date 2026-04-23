from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, Optional

from .alerts import AlertSystem, check_and_alert
from .collectors.cameras import CameraCollector
from .collectors.detectors import DetectorCollector, TomTomFlowCollector
from .collectors.incidents import IncidentCollector, TomTomIncidentCollector
from .collectors.panels import PanelCollector
from .config import (
    DEFAULT_DB_PATH,
    DEFAULT_SNAPSHOTS_DIR,
    TOMTOM_API_KEY,
    TOMTOM_DIRECTION_BASELINE_OFFSET,
)
from .http import HttpClient
from .inference import infer_bridge_state
from .storage import Storage
from .utils import utc_now_iso


class VCentenarioService:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR) -> None:
        self.storage = Storage(db_path)
        self.snapshots_dir = snapshots_dir
        self.logger = logging.getLogger(__name__)
        self._run_lock = threading.Lock()
        http = HttpClient()
        self.panel_collector = PanelCollector(http)
        self.incident_collector = IncidentCollector(http)
        self.tomtom_incident_collector = TomTomIncidentCollector(http)
        self.camera_collector = CameraCollector(http)
        self.detector_collector = DetectorCollector(http)
        self.tomtom_collector = TomTomFlowCollector(http)
        self.alert_system = AlertSystem()

    def init_db(self) -> None:
        self.storage.init_db()

    def run_once(self) -> Dict[str, object]:
        with self._run_lock:
            return self._run_once_locked()

    def get_history(self, days: int = 7) -> List[Dict[str, object]]:
        return self.storage.get_recent_states(days)

    def _run_once_locked(self) -> Dict[str, object]:
        self.storage.init_db()
        collected_at = utc_now_iso()
        source_status: Dict[str, Dict[str, Any]] = {}
        warnings = []

        panel_inventory = {}
        panel_messages = []
        incidents = []
        cameras = {}
        snapshots = []
        detector_inventory = {}
        detector_readings = []

        try:
            panel_inventory = self.panel_collector.fetch_inventory()
            self.storage.upsert_panel_locations(panel_inventory.values())
            source_status["panel_inventory"] = {"status": "ok", "count": len(panel_inventory)}
        except Exception as exc:
            message = f"panel_inventory: {exc}"
            self.logger.exception("Fallo recogiendo inventario de paneles")
            warnings.append(message)
            source_status["panel_inventory"] = {"status": "error", "error": str(exc)}

        if panel_inventory:
            try:
                panel_messages = self.panel_collector.fetch_active_messages(panel_inventory)
                self.storage.insert_panel_messages(collected_at, panel_messages)
                source_status["panel_messages"] = {"status": "ok", "count": len(panel_messages)}
            except Exception as exc:
                message = f"panel_messages: {exc}"
                self.logger.exception("Fallo recogiendo mensajes de paneles")
                warnings.append(message)
                source_status["panel_messages"] = {"status": "error", "error": str(exc)}
        else:
            source_status["panel_messages"] = {
                "status": "skipped",
                "error": "panel inventory unavailable",
            }

        try:
            incidents = self.incident_collector.fetch_bridge_incidents()
            if TOMTOM_API_KEY:
                tomtom_incidents = self.tomtom_incident_collector.fetch_bridge_incidents()
                incidents.extend(tomtom_incidents)
            self.storage.insert_incidents(collected_at, incidents)
            source_status["incidents"] = {"status": "ok", "count": len(incidents)}
        except Exception as exc:
            message = f"incidents: {exc}"
            self.logger.exception("Fallo recogiendo incidencias")
            warnings.append(message)
            source_status["incidents"] = {"status": "error", "error": str(exc)}

        try:
            cameras = self.camera_collector.fetch_inventory()
            self.storage.upsert_cameras(cameras.values())
            source_status["camera_inventory"] = {"status": "ok", "count": len(cameras)}
        except Exception as exc:
            message = f"camera_inventory: {exc}"
            self.logger.exception("Fallo recogiendo inventario de cámaras")
            warnings.append(message)
            source_status["camera_inventory"] = {"status": "error", "error": str(exc)}

        if cameras:
            try:
                previous_payloads = self.storage.latest_camera_payloads(cameras)
                snapshots = self.camera_collector.fetch_snapshots(cameras, self.snapshots_dir, previous_payloads)
                self.storage.insert_camera_snapshots(snapshots)
                source_status["camera_snapshots"] = {"status": "ok", "count": len(snapshots)}
            except Exception as exc:
                message = f"camera_snapshots: {exc}"
                self.logger.exception("Fallo recogiendo snapshots de cámaras")
                warnings.append(message)
                source_status["camera_snapshots"] = {"status": "error", "error": str(exc)}
        else:
            source_status["camera_snapshots"] = {
                "status": "skipped",
                "error": "camera inventory unavailable",
            }

        # TomTom Routing API — velocidad media por sentido (km 10→12 y km 12→10).
        # Los detectores DGT del tramo tienen timestamps congelados desde junio 2025
        # y no publican datos en tiempo real, por lo que se descartan como fuente.
        detector_readings: list = []
        source_status["detector_readings"] = {"status": "skipped", "error": "DGT sensors frozen — using TomTom Routing instead"}
        if TOMTOM_API_KEY:
            # km 10 (37.343820, -5.986923) → km 12 (37.357216, -6.002909): sentido Huelva
            # km 12 (37.357216, -6.002909) → km 10 (37.343820, -5.986923): sentido Cádiz
            tomtom_routes = [
                (37.343820, -5.986923, 37.357216, -6.002909, "tomtom_route_huelva", "positive"),
                (37.357216, -6.002909, 37.343820, -5.986923, "tomtom_route_cadiz",  "negative"),
            ]
            tomtom_readings = []
            for o_lat, o_lon, d_lat, d_lon, det_id, direction in tomtom_routes:
                reading = self.tomtom_collector.fetch_route_speed(
                    o_lat, o_lon, d_lat, d_lon, det_id, direction=direction
                )
                if reading:
                    tomtom_readings.append(reading)
            detector_readings.extend(tomtom_readings)
            if tomtom_readings:
                self.storage.insert_detector_readings(collected_at, tomtom_readings)
            source_status["tomtom_routing"] = {"status": "ok", "count": len(tomtom_readings)}
        else:
            source_status["tomtom_routing"] = {"status": "skipped", "error": "api key not set"}

        recent_states = self.storage.recent_states(limit=48)
        recent_detector_history = self.storage.tomtom_speed_history(hours=2)
        recent_reports = self.storage.recent_reversible_reports(limit=1)
        latest_report = recent_reports[0] if recent_reports else None
        try:
            observed_direction_profile = self.storage.observed_direction_profile(
                days=7,
                baseline_offset=TOMTOM_DIRECTION_BASELINE_OFFSET,
            )
        except Exception:
            observed_direction_profile = None
        state = infer_bridge_state(
            panel_messages,
            incidents,
            snapshots,
            detector_readings,
            recent_states=recent_states,
            recent_detector_history=recent_detector_history,
            latest_report=latest_report,
            observed_direction_profile=observed_direction_profile,
        )
        state.learning_context = self.storage.update_traffic_profile(state)
        state.forecast = self.storage.predict_traffic(
            reference_time=state.generated_at,
            current_state=state,
            recent_states=recent_states + [asdict(state)],
        )
        self.storage.insert_bridge_state(state)
        check_and_alert(state, incidents, self.alert_system)

        counts = {
            "panel_locations": len(panel_inventory),
            "panel_messages": len(panel_messages),
            "incidents": len(incidents),
            "cameras": len(cameras),
            "snapshots": len(snapshots),
            "detector_locations": len(detector_inventory),
            "detector_readings": len(detector_readings),
        }
        self.storage.insert_collection_run(collected_at, counts, source_status, warnings)
        self.storage.maybe_update_daily_stats()

        return {
            "collected_at": collected_at,
            "counts": counts,
            "source_status": source_status,
            "warnings": warnings,
            "state": asdict(state),
        }

    def se30_live_data(self) -> Dict[str, object]:
        """Live fetch del tramo km 10–12 sentido Huelva: DGT (paneles, incidencias, detectores)
        + TomTom almacenado (timer). Usa los mismos filtros geográficos que la recogida principal."""
        from dataclasses import asdict
        errors: Dict[str, str] = {}

        panel_inventory: Dict = {}
        panel_messages: list = []
        try:
            panel_inventory = self.panel_collector.fetch_inventory()
            if panel_inventory:
                panel_messages = self.panel_collector.fetch_active_messages(panel_inventory)
        except Exception as exc:
            errors["panels"] = str(exc)

        incidents: list = []
        try:
            incidents = self.incident_collector.fetch_bridge_incidents()
        except Exception as exc:
            errors["incidents"] = str(exc)

        detector_inventory: Dict = {}
        detector_readings: list = []
        try:
            detector_inventory = self.detector_collector.fetch_inventory()
            if detector_inventory:
                detector_readings = self.detector_collector.fetch_bridge_measurements(detector_inventory)
        except Exception as exc:
            errors["detectors"] = str(exc)

        # TomTom: puntos del timer ya almacenados (frescos), filtrados al tramo km 10-12
        stored_detectors = self.storage.latest_detector_readings(limit=50)
        tomtom: list = [r for r in stored_detectors if r.get("detector_id", "").startswith("tomtom_")]

        if not TOMTOM_API_KEY:
            errors["tomtom"] = "VCENTENARIO_TOMTOM_API_KEY no configurada"

        return {
            "panels": [asdict(p) for p in panel_messages],
            "panel_locations": len(panel_inventory),
            "incidents": [asdict(i) for i in incidents],
            "detectors": [asdict(d) for d in detector_readings],
            "detector_locations": len(detector_inventory),
            "tomtom": tomtom,
            "errors": errors,
            "collected_at": utc_now_iso(),
        }

    def latest_state(self) -> Optional[Dict[str, object]]:
        return self.storage.latest_state()

    def dashboard_data(self) -> Dict[str, object]:
        self.storage.init_db()
        state = self.latest_state()
        trend_states = self.storage.recent_states_since(minutes=1440, limit=288)
        return {
            "state": state,
            "latest_run": self.storage.latest_collection_run(),
            "recent_states": self.storage.recent_states(limit=16),
            "trend_states": trend_states,
            "panels": self.storage.latest_panel_messages(limit=24),
            "incidents": self.storage.latest_incidents(limit=24),
            "cameras": self.storage.latest_cameras(),
            "detectors": self.storage.latest_detector_readings(limit=24),
            "tomtom_speed_history": self.storage.tomtom_speed_history(hours=6),
            "traffic_profiles": list(self.storage.traffic_profiles().values()),
            "reversible_reports": self.storage.recent_reversible_reports(limit=10),
        }
