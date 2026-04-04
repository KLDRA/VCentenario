from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List

from ..config import BRIDGE_AREA, PANELS_INVENTORY_URL, PANELS_NS_V1, PANELS_URL
from ..http import HttpClient
from ..models import PanelLocation, PanelMessage
from ..utils import km_from_meters, parse_float, within_bbox


class PanelCollector:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch_inventory(self) -> Dict[str, PanelLocation]:
        response = self.http.get(PANELS_INVENTORY_URL, accept="application/xml")
        if response.status != 200:
            detail = f": {response.error}" if response.error else ""
            raise RuntimeError(f"Panel inventory request failed with HTTP {response.status}{detail}")
        root = ET.fromstring(response.body)
        locations: Dict[str, PanelLocation] = {}
        for node in root.findall(".//d:predefinedLocation", PANELS_NS_V1):
            location_id = node.attrib.get("id")
            if not location_id:
                continue
            road = self._find_text(node, ".//d:roadNumber")
            km = km_from_meters(self._find_text(node, ".//d:referencePointDistance"))
            direction = self._find_text(node, ".//d:directionRelative")
            latitude = parse_float(self._find_text(node, ".//d:latitude"))
            longitude = parse_float(self._find_text(node, ".//d:longitude"))
            name = self._find_text(node, ".//d:predefinedLocationName/d:value") or location_id
            if not self._is_bridge_location(location_id, road, km, latitude, longitude):
                continue
            locations[location_id] = PanelLocation(
                location_id=location_id,
                name=name,
                road=road or "",
                km=km,
                direction=direction,
                latitude=latitude,
                longitude=longitude,
            )
        return locations

    def fetch_active_messages(self, inventory: Dict[str, PanelLocation]) -> List[PanelMessage]:
        response = self.http.get(PANELS_URL, accept="application/xml")
        if response.status != 200:
            detail = f": {response.error}" if response.error else ""
            raise RuntimeError(f"Panel feed request failed with HTTP {response.status}{detail}")
        root = ET.fromstring(response.body)
        messages: List[PanelMessage] = []
        for situation in root.findall(".//d:situation", PANELS_NS_V1):
            situation_id = situation.attrib.get("id", "")
            for record in situation.findall("./d:situationRecord", PANELS_NS_V1):
                location_id = self._find_text(record, ".//d:predefinedLocationReference")
                if not location_id or location_id not in inventory:
                    continue
                location = inventory[location_id]
                pictograms = [node.text for node in record.findall(".//d:datexPictogram", PANELS_NS_V1) if node.text]
                legends = [node.text for node in record.findall(".//d:vmsLegend", PANELS_NS_V1) if node.text]
                status = self._find_text(record, ".//d:validityStatus")
                created_at = self._find_text(record, ".//d:situationRecordCreationTime")
                messages.append(
                    PanelMessage(
                        situation_id=situation_id,
                        record_id=record.attrib.get("id", ""),
                        location_id=location_id,
                        road=location.road,
                        km=location.km,
                        direction=location.direction,
                        pictograms=pictograms,
                        legends=legends,
                        status=status,
                        created_at=created_at,
                    )
                )
        return messages

    @staticmethod
    def _find_text(node: ET.Element, path: str) -> str:
        found = node.find(path, PANELS_NS_V1)
        return found.text.strip() if found is not None and found.text else ""

    @staticmethod
    def _is_bridge_location(
        location_id: str,
        road: str,
        km: float,
        latitude: float,
        longitude: float,
    ) -> bool:
        if location_id in BRIDGE_AREA.panel_location_ids:
            return True
        if road == BRIDGE_AREA.road and km is not None and BRIDGE_AREA.km_min - 0.6 <= km <= BRIDGE_AREA.km_max + 0.6:
            return True
        return road == BRIDGE_AREA.road and within_bbox(latitude, longitude, BRIDGE_AREA.bbox)
