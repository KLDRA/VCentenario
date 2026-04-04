from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..config import BRIDGE_AREA, COMMON_NS_V3, INCIDENTS_URL
from ..http import HttpClient
from ..models import Incident
from ..utils import overlap_range, parse_float, within_bbox


class IncidentCollector:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def fetch_bridge_incidents(self) -> List[Incident]:
        response = self.http.get(INCIDENTS_URL, accept="application/xml")
        if response.status != 200:
            detail = f": {response.error}" if response.error else ""
            raise RuntimeError(f"Incident feed request failed with HTTP {response.status}{detail}")
        root = ET.fromstring(response.body)
        incidents: List[Incident] = []
        for situation in root.findall(".//sit:situation", COMMON_NS_V3):
            situation_id = situation.attrib.get("id", "")
            overall_severity = self._find_text(situation, "./sit:overallSeverity")
            for record in situation.findall("./sit:situationRecord", COMMON_NS_V3):
                incident = self._parse_record(situation_id, record, overall_severity)
                if incident and self._is_bridge_incident(incident):
                    incidents.append(incident)
        return incidents

    def _parse_record(self, situation_id: str, record: ET.Element, overall_severity: str) -> Optional[Incident]:
        road = self._find_text(record, ".//loc:roadName")
        if not road:
            return None
        direction = self._find_text(record, ".//lse:tpegDirectionRoad") or self._find_text(record, ".//loc:tpegDirection")
        from_km = parse_float(self._find_text(record, ".//loc:from//lse:kilometerPoint"))
        to_km = parse_float(self._find_text(record, ".//loc:to//lse:kilometerPoint"))
        latitude = parse_float(self._find_text(record, ".//loc:from//loc:latitude"))
        longitude = parse_float(self._find_text(record, ".//loc:from//loc:longitude"))
        severity = self._find_text(record, "./sit:severity") or overall_severity
        validity_status = self._find_text(record, ".//com:validityStatus")
        start_time = self._find_text(record, ".//com:overallStartTime")
        end_time = self._find_text(record, ".//com:overallEndTime")
        incident_type = self._extract_incident_type(record)
        cause_type = self._find_text(record, ".//sit:causeType")
        municipality = self._find_text(record, ".//loc:from//lse:municipality") or self._find_text(record, ".//loc:to//lse:municipality")
        province = self._find_text(record, ".//loc:from//lse:province") or self._find_text(record, ".//loc:to//lse:province")
        return Incident(
            situation_id=situation_id,
            record_id=record.attrib.get("id", ""),
            road=road,
            direction=direction or None,
            severity=severity or None,
            validity_status=validity_status or None,
            start_time=start_time or None,
            end_time=end_time or None,
            incident_type=incident_type,
            cause_type=cause_type or None,
            from_km=from_km,
            to_km=to_km,
            latitude=latitude,
            longitude=longitude,
            municipality=municipality or None,
            province=province or None,
        )

    @staticmethod
    def _find_text(node: ET.Element, path: str) -> str:
        found = node.find(path, COMMON_NS_V3)
        return found.text.strip() if found is not None and found.text else ""

    @staticmethod
    def _extract_incident_type(record: ET.Element) -> Optional[str]:
        candidates = (
            ".//sit:roadOrCarriagewayOrLaneManagementType",
            ".//sit:trafficConstrictionType",
            ".//sit:abnormalTrafficType",
            ".//sit:roadMaintenanceType",
            ".//sit:vehicleObstructionType",
            ".//sit:accidentType",
        )
        for path in candidates:
            value = IncidentCollector._find_text(record, path)
            if value:
                return value
        return None

    @staticmethod
    def _is_bridge_incident(incident: Incident) -> bool:
        if incident.road != BRIDGE_AREA.road:
            return False
        if overlap_range(incident.from_km, incident.to_km, BRIDGE_AREA.km_min, BRIDGE_AREA.km_max, margin=1.2):
            return True
        return within_bbox(incident.latitude, incident.longitude, BRIDGE_AREA.bbox)
