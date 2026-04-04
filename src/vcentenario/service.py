from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import threading
from typing import Any, Dict, Optional

from .collectors.cameras import CameraCollector
from .collectors.detectors import DetectorCollector
from .collectors.incidents import IncidentCollector
from .collectors.panels import PanelCollector
from .config import DEFAULT_DB_PATH, DEFAULT_SNAPSHOTS_DIR
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
        self.camera_collector = CameraCollector(http)
        self.detector_collector = DetectorCollector(http)

    def init_db(self) -> None:
        self.storage.init_db()

    def run_once(self) -> Dict[str, object]:
        with self._run_lock:
            return self._run_once_locked()

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

        try:
            detector_inventory = self.detector_collector.fetch_inventory()
            self.storage.upsert_detector_locations(detector_inventory.values())
            source_status["detector_inventory"] = {"status": "ok", "count": len(detector_inventory)}
        except Exception as exc:
            message = f"detector_inventory: {exc}"
            self.logger.exception("Fallo recogiendo inventario de detectores")
            warnings.append(message)
            source_status["detector_inventory"] = {"status": "error", "error": str(exc)}

        if detector_inventory:
            try:
                detector_readings = self.detector_collector.fetch_bridge_measurements(detector_inventory)
                self.storage.insert_detector_readings(collected_at, detector_readings)
                source_status["detector_readings"] = {"status": "ok", "count": len(detector_readings)}
            except Exception as exc:
                message = f"detector_readings: {exc}"
                self.logger.exception("Fallo recogiendo lecturas de detectores")
                warnings.append(message)
                source_status["detector_readings"] = {"status": "error", "error": str(exc)}
        else:
            source_status["detector_readings"] = {
                "status": "skipped",
                "error": "detector inventory unavailable",
            }

        recent_states = self.storage.recent_states(limit=48)
        state = infer_bridge_state(
            panel_messages,
            incidents,
            snapshots,
            detector_readings,
            recent_states=recent_states,
        )
        self.storage.insert_bridge_state(state)

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
        cleanup = self.storage.prune_history()

        return {
            "collected_at": collected_at,
            "counts": counts,
            "source_status": source_status,
            "warnings": warnings,
            "cleanup": cleanup,
            "state": asdict(state),
        }

    def latest_state(self) -> Optional[Dict[str, object]]:
        row = self.storage.latest_state()
        if row is None:
            return None
        data = dict(row)
        data["official"] = bool(data["official"])
        data["evidence"] = json.loads(data.pop("evidence_json"))
        data["breakdown"] = json.loads(data.pop("breakdown_json"))
        return data

    def dashboard_data(self) -> Dict[str, object]:
        self.storage.init_db()
        state = self.latest_state()
        return {
            "state": state,
            "latest_run": self.storage.latest_collection_run(),
            "recent_states": self.storage.recent_states(limit=16),
            "panels": self.storage.latest_panel_messages(limit=24),
            "incidents": self.storage.latest_incidents(limit=24),
            "cameras": self.storage.latest_cameras(),
            "detectors": self.storage.latest_detector_readings(limit=24),
        }
