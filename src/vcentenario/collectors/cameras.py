from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import (
    BRIDGE_AREA,
    CAMERAS_URL,
    CAMERA_DIRECTION_SPLITS,
    COMMON_NS_V3,
    ENABLE_VISION,
    YOLO_CONFIDENCE,
    YOLO_ENABLE_TILING,
    YOLO_IMAGE_SIZE,
    YOLO_MODEL_PATH,
    YOLO_TILE_OVERLAP,
)
from ..http import HttpClient
from ..models import Camera, CameraSnapshot
from ..utils import ensure_dir, parse_float, sampled_byte_change_ratio, sha256_bytes, utc_now_iso, within_bbox

_yolo_model = None
_yolo_load_attempted = False
logger = logging.getLogger(__name__)
_cv2_module = None
_cv2_load_attempted = False


def get_cv2_module() -> Optional[object]:
    global _cv2_load_attempted, _cv2_module
    if _cv2_load_attempted:
        return _cv2_module
    _cv2_load_attempted = True
    try:
        import cv2

        _cv2_module = cv2
    except ImportError:
        _cv2_module = None
    return _cv2_module


def compute_visual_metrics(previous_payload: bytes, current_payload: bytes) -> float:
    byte_change = sampled_byte_change_ratio(previous_payload, current_payload)
    cv2 = get_cv2_module()
    if cv2 is None:
        return byte_change
    try:
        import numpy as np

        previous_img = cv2.imdecode(np.frombuffer(previous_payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        current_img = cv2.imdecode(np.frombuffer(current_payload, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if previous_img is None or current_img is None:
            return byte_change
        height = min(previous_img.shape[0], current_img.shape[0], 256)
        width = min(previous_img.shape[1], current_img.shape[1], 256)
        if height <= 0 or width <= 0:
            return byte_change
        previous_img = cv2.resize(previous_img, (width, height))
        current_img = cv2.resize(current_img, (width, height))
        frame_delta = cv2.absdiff(previous_img, current_img)
        motion_ratio = float(frame_delta.mean()) / 255.0
        prev_edges = cv2.Canny(previous_img, 80, 160)
        curr_edges = cv2.Canny(current_img, 80, 160)
        edge_delta = cv2.absdiff(prev_edges, curr_edges)
        edge_ratio = float(edge_delta.mean()) / 255.0
        return max(0.0, min(1.0, (byte_change * 0.35) + (motion_ratio * 0.4) + (edge_ratio * 0.25)))
    except Exception:
        logger.exception("Fallo calculando métrica visual con OpenCV")
        return byte_change


def _collect_vehicle_detections(result: object, x_offset: float = 0.0, y_offset: float = 0.0) -> List[Tuple[int, float, Tuple[float, float, float, float]]]:
    detections: List[Tuple[int, float, Tuple[float, float, float, float]]] = []
    for box in result.boxes:
        cls = int(box.cls)
        if cls not in (2, 3, 5, 7):
            continue
        x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
        detections.append((cls, float(box.conf), (x1 + x_offset, y1 + y_offset, x2 + x_offset, y2 + y_offset)))
    return detections


def _box_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


def merge_vehicle_detections(
    detections: Sequence[Tuple[int, float, Tuple[float, float, float, float]]],
    iou_threshold: float = 0.45,
) -> List[Tuple[int, float, Tuple[float, float, float, float]]]:
    kept: List[Tuple[int, float, Tuple[float, float, float, float]]] = []
    for detection in sorted(detections, key=lambda item: item[1], reverse=True):
        cls, confidence, box = detection
        if any(_box_iou(box, existing_box) >= iou_threshold for _, _, existing_box in kept):
            continue
        kept.append((cls, confidence, box))
    return kept


def _point_in_polygon(x: float, y: float, polygon: Sequence[Tuple[float, float]]) -> bool:
    inside = False
    if len(polygon) < 3:
        return False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < ((xj - xi) * (y - yi) / ((yj - yi) or 1e-9)) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def count_vehicles_with_yolo(model: object, file_path: Path) -> int:
    return len(detect_vehicles_with_yolo(model, file_path))


def detect_vehicles_with_yolo(
    model: object,
    file_path: Path,
) -> List[Tuple[int, float, Tuple[float, float, float, float]]]:
    from PIL import Image

    detections: List[Tuple[int, float, Tuple[float, float, float, float]]] = []
    full_results = model(str(file_path), verbose=False, conf=YOLO_CONFIDENCE, imgsz=YOLO_IMAGE_SIZE)
    for result in full_results:
        detections.extend(_collect_vehicle_detections(result))

    if YOLO_ENABLE_TILING:
        with Image.open(file_path) as image:
            width, height = image.size
            if width >= 1000 and height >= 600:
                tile_width = max(width // 2, 1)
                tile_height = max(height // 2, 1)
                step_x = max(1, int(tile_width * (1.0 - YOLO_TILE_OVERLAP)))
                step_y = max(1, int(tile_height * (1.0 - YOLO_TILE_OVERLAP)))
                max_x = max(width - tile_width, 0)
                max_y = max(height - tile_height, 0)
                y_positions = sorted({0, step_y, max_y})
                x_positions = sorted({0, step_x, max_x})
                for y_offset in y_positions:
                    for x_offset in x_positions:
                        crop = image.crop((x_offset, y_offset, x_offset + tile_width, y_offset + tile_height))
                        tile_results = model(crop, verbose=False, conf=YOLO_CONFIDENCE, imgsz=YOLO_IMAGE_SIZE)
                        for result in tile_results:
                            detections.extend(_collect_vehicle_detections(result, float(x_offset), float(y_offset)))

    return merge_vehicle_detections(detections)


def classify_vehicle_directions(
    camera_id: str,
    detections: Sequence[Tuple[int, float, Tuple[float, float, float, float]]],
) -> Dict[str, int]:
    profile = CAMERA_DIRECTION_SPLITS.get(camera_id)
    if not profile:
        return {}
    axis = str(profile.get("axis", "y")).lower()
    split = float(profile["split"])
    low_label = str(profile["low_label"])
    high_label = str(profile["high_label"])
    counts = {low_label: 0, high_label: 0}
    zones = profile.get("zones", [])
    for _, _, (x1, y1, x2, y2) in detections:
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        assigned = False
        for zone in zones:
            polygon = zone.get("polygon", [])
            label = str(zone.get("label", ""))
            if label in counts and _point_in_polygon(center_x, center_y, polygon):
                counts[label] += 1
                assigned = True
                break
        if assigned:
            continue
        center = center_x if axis == "x" else center_y
        if center < split:
            counts[low_label] += 1
        else:
            counts[high_label] += 1
    return counts


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
            vehicle_count = None
            content_length = len(response.body)
            if response.status == 200 and response.headers.get("content-type", "").startswith("image/"):
                sha256 = sha256_bytes(response.body)
                file_name = f"{camera.camera_id}_{fetched_at.replace(':', '').replace('+', '_')}.jpg"
                file_path = snapshots_dir / file_name
                file_path.write_bytes(response.body)
                image_path = str(file_path)
                previous_payload = previous_payloads.get(camera.camera_id)
                if previous_payload is not None:
                    visual_change_score = compute_visual_metrics(previous_payload, response.body)

                model = get_yolo_model()
                if model is not None:
                    try:
                        detections = detect_vehicles_with_yolo(model, file_path)
                        vehicle_count = len(detections)
                        vehicle_counts_by_direction = classify_vehicle_directions(camera.camera_id, detections)
                    except Exception:
                        vehicle_count = None
                        vehicle_counts_by_direction = {}
                else:
                    vehicle_counts_by_direction = {}
            else:
                vehicle_counts_by_direction = {}
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
                    vehicle_counts_by_direction=vehicle_counts_by_direction,
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
