from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from .models import BridgeState, CameraSnapshot, Incident, PanelMessage
from .utils import clamp, utc_now_iso


SEVERITY_WEIGHT = {
    "lowest": 2.0,
    "low": 5.0,
    "medium": 12.0,
    "high": 20.0,
    "highest": 28.0,
}

INCIDENT_TYPE_WEIGHT = {
    "roadClosed": 22.0,
    "laneClosures": 14.0,
    "narrowLanes": 12.0,
    "singleAlternateLineTraffic": 18.0,
    "doNotUseSpecifiedLanesOrCarriageways": 14.0,
    "lanesDeviated": 12.0,
    "newRoadworksLayout": 8.0,
    "roadworks": 8.0,
}

PANEL_KEYWORDS = {
    "ACCIDENT": 16.0,
    "RETENCION": 16.0,
    "RETENCIONES": 16.0,
    "CONGESTION": 16.0,
    "OBRAS": 10.0,
    "CORTADO": 18.0,
    "DESVIO": 8.0,
    "LENTO": 10.0,
}

PICTOGRAM_WEIGHT = {
    "accident": 18.0,
    "roadworks": 10.0,
    "maximumSpeedLimit": 4.0,
    "blankVoid": 0.0,
}


def infer_bridge_state(
    panels: Iterable[PanelMessage],
    incidents: Iterable[Incident],
    snapshots: Iterable[CameraSnapshot],
) -> BridgeState:
    panels = list(panels)
    incidents = list(incidents)
    snapshots = list(snapshots)
    breakdown: Dict[str, float] = defaultdict(float)
    direction_pressure: Dict[str, float] = defaultdict(float)
    evidence: List[str] = []

    for panel in panels:
        panel_score = 0.0
        for legend in panel.legends:
            upper = legend.upper()
            for keyword, weight in PANEL_KEYWORDS.items():
                if keyword in upper:
                    panel_score += weight
        for pictogram in panel.pictograms:
            panel_score += PICTOGRAM_WEIGHT.get(pictogram, 2.0)
        if panel_score == 0 and any("CENTENARIO" in legend.upper() for legend in panel.legends):
            panel_score = 4.0
        if panel_score == 0:
            continue
        breakdown["panels"] += panel_score
        if panel.direction:
            direction_pressure[panel.direction] += panel_score
        if panel.legends:
            evidence.append(f"panel:{panel.location_id}:{'/'.join(panel.legends[:2])}")

    for incident in incidents:
        incident_score = SEVERITY_WEIGHT.get((incident.severity or "").lower(), 8.0)
        incident_score += INCIDENT_TYPE_WEIGHT.get(incident.incident_type or "", 6.0)
        breakdown["incidents"] += incident_score
        if incident.direction:
            direction_pressure[incident.direction] += incident_score
        label = incident.incident_type or incident.cause_type or "incident"
        evidence.append(f"incident:{incident.road}:{label}")

    active_cameras = 0
    unavailable_cameras = 0
    visual_change_total = 0.0
    vehicle_total = 0
    for snapshot in snapshots:
        if snapshot.http_status == 200:
            active_cameras += 1
            if snapshot.visual_change_score is not None:
                visual_change_total += snapshot.visual_change_score * 12.0
            if snapshot.vehicle_count is not None:
                vehicle_total += snapshot.vehicle_count
        else:
            unavailable_cameras += 1
    if active_cameras:
        breakdown["camera_availability"] += min(active_cameras * 2.0, 6.0)
    if visual_change_total:
        breakdown["camera_change"] += min(visual_change_total, 10.0)
        evidence.append("camera:visual-change")
    if vehicle_total:
        breakdown["vehicle_count"] += min(vehicle_total * 2.5, 35.0)
        evidence.append(f"camera:vehicles:{vehicle_total}")
    if unavailable_cameras:
        evidence.append(f"camera:unavailable:{unavailable_cameras}")

    traffic_score = round(sum(breakdown.values()), 2)
    traffic_level = classify_traffic_level(traffic_score)
    reversible_probable, confidence, direction_evidence = infer_reversible(direction_pressure, panels, incidents)
    evidence.extend(direction_evidence)
    deduped_evidence = list(dict.fromkeys(evidence))
    return BridgeState(
        generated_at=utc_now_iso(),
        traffic_score=traffic_score,
        traffic_level=traffic_level,
        reversible_probable=reversible_probable,
        confidence=confidence,
        official=False,
        evidence=deduped_evidence,
        breakdown=dict(sorted(breakdown.items())),
    )


def classify_traffic_level(score: float) -> str:
    if score < 15:
        return "fluido"
    if score < 35:
        return "denso"
    if score < 60:
        return "retenciones"
    return "congestion_fuerte"


def infer_reversible(
    direction_pressure: Dict[str, float],
    panels: List[PanelMessage],
    incidents: List[Incident],
) -> tuple[str, float, List[str]]:
    if not direction_pressure:
        return "indeterminado", 0.15, ["reversible:no-directional-signal"]
    ordered = sorted(direction_pressure.items(), key=lambda item: item[1], reverse=True)
    lead_direction, lead_score = ordered[0]
    other_score = ordered[1][1] if len(ordered) > 1 else 0.0
    difference = lead_score - other_score
    confidence = clamp(0.2 + (difference / max(lead_score, 1.0)) * 0.45, 0.2, 0.78)
    evidence = [f"reversible:pressure:{lead_direction}:{lead_score:.1f}"]
    panel_hits = sum(1 for panel in panels if panel.direction == lead_direction)
    incident_hits = sum(1 for incident in incidents if incident.direction == lead_direction)
    if panel_hits:
        confidence += 0.07
        evidence.append(f"reversible:panel-hits:{panel_hits}")
    if incident_hits:
        confidence += 0.07
        evidence.append(f"reversible:incident-hits:{incident_hits}")
    confidence = round(clamp(confidence, 0.2, 0.85), 2)
    if difference < 8.0:
        return "indeterminado", confidence - 0.08, evidence + ["reversible:low-asymmetry"]
    return lead_direction, confidence, evidence
