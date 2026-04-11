from __future__ import annotations

from datetime import datetime
import json
import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from ..config import (
    BRIDGE_AREA,
    DETECTOR_MAX_AGE,
    DETECTORS_INVENTORY_URL,
    DETECTORS_NS_V1,
    DETECTORS_URL,
    TOMTOM_API_KEY,
    TOMTOM_FLOW_URL,
)
from ..http import HttpClient
from ..models import DetectorLocation, DetectorReading
from ..utils import km_from_meters, parse_float, within_bbox
logger = logging.getLogger(__name__)


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
            # El feed DGT publica timestamps congelados (sin actualizar) pero los valores
            # de velocidad y flujo son en tiempo real. Omitimos el chequeo de antigüedad:
            # la frescura queda garantizada por el momento en que se hace la petición HTTP.
            flow_value = parse_float(self._find_text(node, ".//d:vehicleFlow"))
            avg_speed = parse_float(self._find_text(node, ".//d:averageVehicleSpeed"))
            # Ignorar detectores que reportan todo a cero — están apagados o sin señal
            if avg_speed == 0.0 and (flow_value is None or flow_value == 0.0):
                continue
            readings.append(
                DetectorReading(
                    detector_id=detector_id,
                    measured_at=measured_at,
                    road=location.road,
                    km=location.km,
                    direction=location.direction,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    average_speed=avg_speed,
                    vehicle_flow=int(flow_value) if flow_value is not None else None,
                    occupancy=parse_float(self._find_text(node, ".//d:occupancy")),
                )
            )
        if not readings:
            logger.warning(
                "Detector feed %s devolvió 0 mediciones (última comprobación %s)",
                DETECTORS_URL,
                datetime.now().isoformat(),
            )
        return readings

    def fetch_se30_inventory(self) -> Dict[str, DetectorLocation]:
        """Fetches all detector locations on SE-30 (no km/bbox filter)."""
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
            if road != BRIDGE_AREA.road:
                continue
            km = km_from_meters(self._find_text(node, ".//d:referencePointDistance"))
            direction = self._find_text(node, ".//d:directionRelative")
            latitude = parse_float(self._find_text(node, ".//d:latitude"))
            longitude = parse_float(self._find_text(node, ".//d:longitude"))
            locations[detector_id] = DetectorLocation(
                detector_id=detector_id,
                road=road or None,
                km=km,
                direction=direction or None,
                latitude=latitude,
                longitude=longitude,
            )
        return locations

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


class TomTomFlowCollector:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch_flow_at_point(
        self,
        lat: float,
        lon: float,
        detector_id: str,
        direction: Optional[str] = None,
        heading: Optional[int] = None,
    ) -> Optional[DetectorReading]:
        if not TOMTOM_API_KEY:
            logger.warning("TomTom API Key no configurada, saltando recolección de flujo")
            return None

        url = f"{TOMTOM_FLOW_URL}?point={lat},{lon}&unit=KMPH&key={TOMTOM_API_KEY}"
        if heading is not None:
            url += f"&heading={heading}"
        response = self.http.get(url, accept="application/json")
        if response.status != 200:
            logger.error("Error en TomTom Flow API (HTTP %d): %s", response.status, response.error)
            return None

        try:
            data = json.loads(response.body)
            flow = data.get("flowSegmentData")
            if not flow:
                return None

            current_speed = parse_float(str(flow.get("currentSpeed")))
            free_flow_speed = parse_float(str(flow.get("freeFlowSpeed")))

            return DetectorReading(
                detector_id=detector_id,
                measured_at=datetime.now().isoformat(),
                road="SE-30",
                km=None,
                direction=direction,
                latitude=lat,
                longitude=lon,
                average_speed=current_speed,
                vehicle_flow=None,
                occupancy=None,
                source="tomtom",
                free_flow_speed=free_flow_speed,
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.error("Error al procesar respuesta de TomTom Flow: %s", exc)
            return None

    def fetch_route_speed(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        detector_id: str,
        direction: str,
    ) -> Optional[DetectorReading]:
        """Calcula velocidad media de un tramo mediante la Routing API de TomTom.
        Devuelve datos diferenciados por sentido de la marcha.
        vehicle_flow se reutiliza para almacenar el retardo en segundos (trafficDelayInSeconds).
        """
        if not TOMTOM_API_KEY:
            return None
        url = (
            f"https://api.tomtom.com/routing/1/calculateRoute"
            f"/{origin_lat},{origin_lon}:{dest_lat},{dest_lon}/json"
            f"?traffic=true&travelMode=car&routeType=fastest"
            f"&computeTravelTimeFor=all&key={TOMTOM_API_KEY}"
        )
        response = self.http.get(url, accept="application/json")
        if response.status != 200:
            logger.error("Error en TomTom Routing API (HTTP %d): %s", response.status, response.error)
            return None
        try:
            data = json.loads(response.body)
            summary = data["routes"][0]["summary"]
            length_m = summary["lengthInMeters"]
            travel_s = summary["travelTimeInSeconds"]
            delay_s = int(summary.get("trafficDelayInSeconds", 0))
            no_traffic_s = summary.get("noTrafficTravelTimeInSeconds", travel_s)

            current_speed = round((length_m / travel_s) * 3.6, 1) if travel_s else None
            free_speed = round((length_m / no_traffic_s) * 3.6, 1) if no_traffic_s else None

            return DetectorReading(
                detector_id=detector_id,
                measured_at=datetime.now().isoformat(),
                road="SE-30",
                km=None,
                direction=direction,
                latitude=None,
                longitude=None,
                average_speed=current_speed,
                vehicle_flow=delay_s,   # campo reutilizado: retardo en segundos
                occupancy=None,
                source="tomtom",
                free_flow_speed=free_speed,
            )
        except (json.JSONDecodeError, KeyError, ValueError, IndexError) as exc:
            logger.error("Error al procesar respuesta de TomTom Routing: %s", exc)
            return None
