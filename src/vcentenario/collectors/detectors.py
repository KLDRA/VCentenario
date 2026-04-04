from __future__ import annotations

from datetime import datetime
import xml.etree.ElementTree as ET
from typing import Dict, List

from ..config import (
    BRIDGE_AREA,
    DETECTOR_MAX_AGE,
    DETECTORS_INVENTORY_URL,
    DETECTORS_NS_V1,
    DETECTORS_URL,
)
from ..http import HttpClient
from ..models import DetectorLocation, DetectorReading
from ..utils import km_from_meters, parse_float, within_bbox


class DetectorCollector:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch_inventory(self) -> Dict[str, DetectorLocation]:
        response = self.http.get(DETECTORS_INVENTORY_URL, accept="application/xml")
        if response.status != 200:
            detail = f": {response.error}" if response.error else ""
            raise RuntimeError(f"Detector inventory request failed with HTTP {response.status}{detail}")
        root = ET.fromstring(response.body)
        locations: Dict[str, DetectorLocation] = {}
        for node in root.findall(".//d:predefinedLocation", DETECTORS_NS_V1):
            detector_id = node.attrib.get("id")
            if not detector_id:
                continue
            road = self._find_text(node, ".//d:roadNumber")
            km = km_from_meters(self._find_text(node, ".//d:referencePointDistance"))
            direction = self._find_text(node, ".//d:directionRelative")
            latitude = parse_float(self._find_text(node, ".//d:latitude"))
            longitude = parse_float(self._find_text(node, ".//d:longitude"))
            if not self._is_bridge_detector(detector_id, road, km, latitude, longitude):
                continue
            locations[detector_id] = DetectorLocation(
                detector_id=detector_id,
                road=road or None,
                km=km,
                direction=direction or None,
                latitude=latitude,
                longitude=longitude,
            )
        return locations

    def fetch_bridge_measurements(self, inventory: Dict[str, DetectorLocation]) -> List[DetectorReading]:
        if not inventory:
            return []
        response = self.http.get(DETECTORS_URL, accept="application/xml")
        if response.status != 200:
            detail = f": {response.error}" if response.error else ""
            raise RuntimeError(f"Detector feed request failed with HTTP {response.status}{detail}")
        root = ET.fromstring(response.body)
        readings: List[DetectorReading] = []
        for node in root.findall(".//d:siteMeasurements", DETECTORS_NS_V1):
            detector_id = self._find_text(node, ".//d:measurementSiteReference")
            if not detector_id or detector_id not in inventory:
                continue
            location = inventory[detector_id]
            measured_at = self._find_text(node, ".//d:measurementTimeDefault") or None
            if self._is_stale_measurement(measured_at):
                continue
            flow_value = parse_float(self._find_text(node, ".//d:vehicleFlow"))
            readings.append(
                DetectorReading(
                    detector_id=detector_id,
                    measured_at=measured_at,
                    road=location.road,
                    km=location.km,
                    direction=location.direction,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    average_speed=parse_float(self._find_text(node, ".//d:averageVehicleSpeed")),
                    vehicle_flow=int(flow_value) if flow_value is not None else None,
                    occupancy=parse_float(self._find_text(node, ".//d:occupancy")),
                )
            )
        return readings

    @staticmethod
    def _find_text(node: ET.Element, path: str) -> str:
        found = node.find(path, DETECTORS_NS_V1)
        return found.text.strip() if found is not None and found.text else ""

    @staticmethod
    def _is_bridge_detector(
        detector_id: str,
        road: str,
        km: float,
        latitude: float,
        longitude: float,
    ) -> bool:
        if detector_id in BRIDGE_AREA.preferred_detector_ids:
            return True
        if road == BRIDGE_AREA.road and km is not None and BRIDGE_AREA.km_min - 1.0 <= km <= BRIDGE_AREA.km_max + 1.0:
            return True
        return road == BRIDGE_AREA.road and within_bbox(latitude, longitude, BRIDGE_AREA.bbox)

    @staticmethod
    def _is_stale_measurement(measured_at: str | None) -> bool:
        if not measured_at:
            return True
        try:
            timestamp = datetime.fromisoformat(measured_at)
        except ValueError:
            return True
        if timestamp.tzinfo is None:
            return True
        age = datetime.now(timestamp.tzinfo) - timestamp
        return age > DETECTOR_MAX_AGE
