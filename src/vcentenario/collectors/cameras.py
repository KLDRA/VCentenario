from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from ..config import BRIDGE_AREA, CAMERAS_URL, COMMON_NS_V3, ENABLE_VISION, YOLO_MODEL_PATH
from ..http import HttpClient
from ..models import Camera, CameraSnapshot
from ..utils import ensure_dir, parse_float, sampled_byte_change_ratio, sha256_bytes, utc_now_iso, within_bbox

_yolo_model = None
_yolo_load_attempted = False
logger = logging.getLogger(__name__)


def get_yolo_model() -> Optional[object]:
    global _yolo_load_attempted, _yolo_model
    if not ENABLE_VISION:
        return None
    if YOLO_MODEL_PATH is None or not YOLO_MODEL_PATH.exists():
        return None
    if _yolo_load_attempted and _yolo_model is None:
        return None
    if _yolo_model is None:
        _yolo_load_attempted = True
        try:
            from ultralytics import YOLO

            _yolo_model = YOLO(str(YOLO_MODEL_PATH))
        except ImportError:
            logger.warning(
                "Conteo de vehículos desactivado: instala el extra 'vision' para usar YOLO (%s)",
                YOLO_MODEL_PATH,
            )
            return None
        except Exception:
            logger.exception("No se pudo cargar el modelo YOLO desde %s", YOLO_MODEL_PATH)
            return None
    return _yolo_model


class CameraCollector:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch_inventory(self) -> Dict[str, Camera]:
        response = self.http.get(CAMERAS_URL, accept="application/xml")
        if response.status != 200:
            detail = f": {response.error}" if response.error else ""
            raise RuntimeError(f"Camera inventory request failed with HTTP {response.status}{detail}")
        root = ET.fromstring(response.body)
        cameras: Dict[str, Camera] = {}
        for node in root.findall(".//ns2:device", COMMON_NS_V3):
            if self._find_text(node, "./ns2:typeOfDevice") != "camera":
                continue
            camera_id = node.attrib.get("id")
            if not camera_id:
                continue
            road = self._find_text(node, ".//loc:roadName")
            km = parse_float(self._find_text(node, ".//lse:kilometerPoint"))
            direction = self._find_text(node, ".//lse:tpegDirectionRoad")
            latitude = parse_float(self._find_text(node, ".//loc:latitude"))
            longitude = parse_float(self._find_text(node, ".//loc:longitude"))
            image_url = self._find_text(node, ".//fse:deviceUrl")
            if not image_url:
                continue
            if not self._is_bridge_camera(camera_id, road, km, latitude, longitude):
                continue
            cameras[camera_id] = Camera(
                camera_id=camera_id,
                road=road or None,
                km=km,
                direction=direction or None,
                latitude=latitude,
                longitude=longitude,
                image_url=image_url,
            )
        return cameras

    def fetch_snapshots(
        self,
        cameras: Dict[str, Camera],
        snapshots_dir: Path,
        previous_payloads: Optional[Dict[str, bytes]] = None,
    ) -> List[CameraSnapshot]:
        ensure_dir(snapshots_dir)
        previous_payloads = previous_payloads or {}
        results: List[CameraSnapshot] = []
        fetched_at = utc_now_iso()
        for camera in cameras.values():
            response = self.http.get(camera.image_url, accept="image/jpeg")
            image_path: Optional[str] = None
            sha256: Optional[str] = None
            visual_change_score: Optional[float] = None
            content_length = len(response.body)
            if response.status == 200 and response.headers.get("content-type", "").startswith("image/"):
                sha256 = sha256_bytes(response.body)
                file_name = f"{camera.camera_id}_{fetched_at.replace(':', '').replace('+', '_')}.jpg"
                file_path = snapshots_dir / file_name
                file_path.write_bytes(response.body)
                image_path = str(file_path)
                previous_payload = previous_payloads.get(camera.camera_id)
                if previous_payload is not None:
                    visual_change_score = sampled_byte_change_ratio(previous_payload, response.body)

                vehicle_count = None
                model = get_yolo_model()
                if model is not None:
                    try:
                        results_yolo = model(str(file_path), verbose=False)
                        vehicle_count = 0
                        for r in results_yolo:
                            # COCO classes: 2:car, 3:motorcycle, 5:bus, 7:truck
                            for box in r.boxes:
                                if int(box.cls) in (2, 3, 5, 7):
                                    vehicle_count += 1
                    except Exception:
                        vehicle_count = None
            results.append(
                CameraSnapshot(
                    camera_id=camera.camera_id,
                    fetched_at=fetched_at,
                    http_status=response.status,
                    content_length=content_length,
                    sha256=sha256,
                    image_path=image_path,
                    last_modified=response.headers.get("last-modified"),
                    visual_change_score=visual_change_score,
                    vehicle_count=vehicle_count,
                )
            )
        return results

    @staticmethod
    def _find_text(node: ET.Element, path: str) -> str:
        found = node.find(path, COMMON_NS_V3)
        return found.text.strip() if found is not None and found.text else ""

    @staticmethod
    def _is_bridge_camera(
        camera_id: str,
        road: str,
        km: float,
        latitude: float,
        longitude: float,
    ) -> bool:
        if camera_id in BRIDGE_AREA.preferred_camera_ids:
            return True
        if road == BRIDGE_AREA.road and km is not None and BRIDGE_AREA.km_min - 1.0 <= km <= BRIDGE_AREA.km_max + 1.0:
            return True
        return within_bbox(latitude, longitude, BRIDGE_AREA.bbox)
