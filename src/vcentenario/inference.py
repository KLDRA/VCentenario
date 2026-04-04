from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import REVERSIBLE_PERSISTENCE_WINDOW, REVERSIBLE_SCHEDULE
from .models import BridgeState, CameraSnapshot, DetectorReading, Incident, PanelMessage
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

DETECTOR_FLOW_WEIGHT = 0.015
DETECTOR_OCCUPANCY_WEIGHT = 0.35
DETECTOR_SLOW_SPEED_WEIGHT = 0.7
DETECTOR_DIRECTION_BIAS_WEIGHT = 10.0
PERSISTENT_BASELINE_SCALE = 0.15
CALIBRATION_EXCLUDED_SOURCES = {"camera_availability", "camera_change", "vehicle_count"}


def infer_bridge_state(
    panels: Iterable[PanelMessage],
    incidents: Iterable[Incident],
    snapshots: Iterable[CameraSnapshot],
    detectors: Iterable[DetectorReading] = (),
    recent_states: Optional[Sequence[Dict[str, object]]] = None,
) -> BridgeState:
    panels = list(panels)
    incidents = list(incidents)
    snapshots = list(snapshots)
    detectors = list(detectors)
    recent_states = list(recent_states or [])
    breakdown: Dict[str, float] = defaultdict(float)
    direction_pressure: Dict[str, float] = defaultdict(float)
    evidence: List[str] = []

    for panel in panels:
        panel_score = 0.0
        panel_evidence = f"panel:{panel.location_id}:{'/'.join(panel.legends[:2])}" if panel.legends else None
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
        if panel_evidence and is_persistent_operational_panel(panel, panel_evidence, recent_states):
            panel_score *= PERSISTENT_BASELINE_SCALE
            evidence.append(f"baseline:{panel.location_id}:panel")
        breakdown["panels"] += panel_score
        if panel.direction:
            direction_pressure[panel.direction] += panel_score
        if panel_evidence:
            evidence.append(panel_evidence)

    for incident in incidents:
        incident_score = SEVERITY_WEIGHT.get((incident.severity or "").lower(), 8.0)
        incident_score += INCIDENT_TYPE_WEIGHT.get(incident.incident_type or "", 6.0)
        incident_label = incident.incident_type or incident.cause_type or "incident"
        incident_evidence = f"incident:{incident.road}:{incident_label}"
        if is_persistent_operational_incident(incident, incident_evidence, recent_states):
            incident_score *= PERSISTENT_BASELINE_SCALE
            evidence.append(f"baseline:{incident_label}:incident")
        breakdown["incidents"] += incident_score
        if incident.direction:
            direction_pressure[incident.direction] += incident_score
        evidence.append(incident_evidence)

    active_cameras = 0
    unavailable_cameras = 0
    visual_change_total = 0.0
    vehicle_total = 0
    for snapshot in snapshots:
        if snapshot.http_status == 200:
            active_cameras += 1
            if snapshot.visual_change_score is not None:
                # Visual change is noisy with lighting and compression artifacts,
                # so it should only add light pressure on its own.
                visual_change_total += snapshot.visual_change_score * 8.0
            if snapshot.vehicle_count is not None:
                directional_counts = snapshot.vehicle_counts_by_direction or {}
                vehicle_total += max(directional_counts.values(), default=snapshot.vehicle_count)
        else:
            unavailable_cameras += 1
    if active_cameras:
        breakdown["camera_availability"] += min(active_cameras * 2.0, 6.0)
    if visual_change_total:
        breakdown["camera_change"] += min(visual_change_total, 3.0)
        evidence.append("camera:visual-change")
    if vehicle_total:
        breakdown["vehicle_count"] += score_camera_traffic(vehicle_total)
        evidence.append(f"camera:vehicles:{vehicle_total}")
    if unavailable_cameras:
        evidence.append(f"camera:unavailable:{unavailable_cameras}")

    detector_score, detector_evidence, detector_direction_pressure = score_detectors(detectors)
    if detector_score:
        breakdown["detectors"] += detector_score
        evidence.extend(detector_evidence)
        for direction, score in detector_direction_pressure.items():
            direction_pressure[direction] += score

    apply_historical_calibration(breakdown, recent_states, evidence)
    traffic_score = round(sum(breakdown.values()), 2)
    traffic_level = classify_traffic_level(traffic_score)
    reversible_probable, confidence, direction_evidence = infer_reversible(
        direction_pressure,
        panels,
        incidents,
        recent_states=recent_states,
        persistence_window=REVERSIBLE_PERSISTENCE_WINDOW,
        schedule=REVERSIBLE_SCHEDULE,
    )
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
    recent_states: Optional[Sequence[Dict[str, object]]] = None,
    persistence_window: int = 8,
    schedule: str = "",
) -> tuple[str, float, List[str]]:
    recent_states = list(recent_states or [])
    direction_pressure = defaultdict(float, direction_pressure)
    evidence: List[str] = []

    schedule_direction, schedule_weight = get_schedule_bias(schedule)
    if schedule_direction:
        direction_pressure[schedule_direction] += schedule_weight
        evidence.append(f"reversible:schedule:{schedule_direction}:{schedule_weight:.1f}")

    persisted_direction, persisted_weight, persistence_evidence = get_persistence_bias(
        recent_states,
        persistence_window=max(1, persistence_window),
    )
    evidence.extend(persistence_evidence)
    if persisted_direction:
        direction_pressure[persisted_direction] += persisted_weight

    if not direction_pressure:
        return "indeterminado", 0.15, evidence + ["reversible:no-directional-signal"]

    ordered = sorted(direction_pressure.items(), key=lambda item: item[1], reverse=True)
    lead_direction, lead_score = ordered[0]
    other_score = ordered[1][1] if len(ordered) > 1 else 0.0
    difference = lead_score - other_score
    confidence = clamp(0.2 + (difference / max(lead_score, 1.0)) * 0.45, 0.2, 0.78)
    evidence.append(f"reversible:pressure:{lead_direction}:{lead_score:.1f}")
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
        return "indeterminado", round(max(0.2, confidence - 0.08), 2), evidence + ["reversible:low-asymmetry"]
    return lead_direction, confidence, evidence


def score_detectors(detectors: Sequence[DetectorReading]) -> Tuple[float, List[str], Dict[str, float]]:
    if not detectors:
        return 0.0, [], {}
    score = 0.0
    evidence: List[str] = []
    direction_pressure: Dict[str, float] = defaultdict(float)
    active_count = 0
    for detector in detectors:
        if detector.average_speed is None and detector.vehicle_flow is None and detector.occupancy is None:
            continue
        active_count += 1
        local_score = 0.0
        if detector.vehicle_flow is not None:
            local_score += min(detector.vehicle_flow * DETECTOR_FLOW_WEIGHT, 18.0)
        if detector.occupancy is not None:
            local_score += min(detector.occupancy * DETECTOR_OCCUPANCY_WEIGHT, 16.0)
        if detector.average_speed is not None and detector.average_speed < 80:
            local_score += min((80 - detector.average_speed) * DETECTOR_SLOW_SPEED_WEIGHT, 24.0)
        score += local_score
        if detector.direction:
            direction_pressure[detector.direction] += min(local_score, DETECTOR_DIRECTION_BIAS_WEIGHT)
    if active_count:
        evidence.append(f"detectors:active:{active_count}")
    if score:
        evidence.append(f"detectors:score:{score:.1f}")
    return score, evidence, direction_pressure


def is_persistent_operational_panel(
    panel: PanelMessage,
    panel_evidence: str,
    recent_states: Sequence[Dict[str, object]],
) -> bool:
    text = " ".join(panel.legends).upper()
    is_informational_bridge_panel = (
        "CENTENARIO" in text
        and not any(keyword in text for keyword in ("RETENCION", "RETENCIONES", "CONGESTION", "ACCIDENT", "CORTADO"))
    )
    looks_permanent = (
        "OBRAS" in text
        or ("DESVIO" in text and "20T" in text)
        or ("OBLIGATORIO" in text and "20T" in text)
        or "roadworks" in panel.pictograms
        or is_informational_bridge_panel
    )
    if not looks_permanent:
        return False
    return evidence_seen_frequently(panel_evidence, recent_states)


def is_persistent_operational_incident(
    incident: Incident,
    incident_evidence: str,
    recent_states: Sequence[Dict[str, object]],
) -> bool:
    looks_permanent = (incident.incident_type or "") in {
        "roadworks",
        "newRoadworksLayout",
        "weightRestrictionInOperation",
    } or (incident.cause_type or "") in {"roadMaintenance", "maintenanceWorks"}
    if not looks_permanent:
        return False
    return evidence_seen_frequently(incident_evidence, recent_states)


def evidence_seen_frequently(evidence_key: str, recent_states: Sequence[Dict[str, object]], threshold: int = 4) -> bool:
    hits = 0
    for state in recent_states[-8:]:
        values = state.get("evidence", [])
        if isinstance(values, list) and evidence_key in values:
            hits += 1
    return hits >= threshold


def apply_historical_calibration(
    breakdown: Dict[str, float],
    recent_states: Sequence[Dict[str, object]],
    evidence: List[str],
) -> None:
    if len(recent_states) < 6:
        return
    calibration_delta = 0.0
    for source_name, current_score in list(breakdown.items()):
        if source_name in CALIBRATION_EXCLUDED_SOURCES:
            continue
        history_values = [
            float(state.get("breakdown", {}).get(source_name, 0.0))
            for state in recent_states
            if isinstance(state.get("breakdown"), dict)
        ]
        history_values = [value for value in history_values if value > 0]
        if len(history_values) < 4:
            continue
        baseline = sorted(history_values)[len(history_values) // 2]
        if baseline <= 0:
            continue
        ratio = clamp(current_score / baseline, 0.65, 1.35)
        adjusted_score = current_score * ratio
        calibration_delta += adjusted_score - current_score
    if calibration_delta:
        breakdown["historical_calibration"] += round(calibration_delta, 2)
        evidence.append(f"calibration:delta:{calibration_delta:.2f}")


def score_camera_traffic(vehicle_count: int) -> float:
    if vehicle_count <= 2:
        return 0.5
    if vehicle_count <= 4:
        return 1.0
    if vehicle_count <= 6:
        return 2.0
    if vehicle_count <= 8:
        return 3.0
    if vehicle_count <= 12:
        return 5.0
    if vehicle_count <= 16:
        return 8.0
    return 12.0


def get_persistence_bias(
    recent_states: Sequence[Dict[str, object]],
    persistence_window: int,
) -> Tuple[Optional[str], float, List[str]]:
    directional_states = [
        state
        for state in recent_states[-persistence_window:]
        if state.get("reversible_probable") in {"positive", "negative"}
    ]
    if len(directional_states) < 2:
        return None, 0.0, []
    counts: Dict[str, int] = defaultdict(int)
    confidence_total = 0.0
    for state in directional_states:
        counts[str(state["reversible_probable"])] += 1
        confidence_total += float(state.get("confidence", 0.0) or 0.0)
    lead_direction, lead_count = max(counts.items(), key=lambda item: item[1])
    if lead_count < max(2, (len(directional_states) // 2) + 1):
        return None, 0.0, []
    average_confidence = confidence_total / max(len(directional_states), 1)
    weight = round(lead_count * average_confidence * 2.2, 2)
    return lead_direction, weight, [f"reversible:persistence:{lead_direction}:{lead_count}"]


def get_schedule_bias(schedule: str) -> Tuple[Optional[str], float]:
    if not schedule.strip():
        return None, 0.0
    now = datetime.now()
    weekday = now.weekday()
    current_minutes = now.hour * 60 + now.minute
    for raw_rule in schedule.split(";"):
        rule = raw_rule.strip()
        if not rule or "=" not in rule or "@" not in rule:
            continue
        left, direction = rule.split("=", 1)
        days, time_range = left.split("@", 1)
        if not _matches_days(days.strip(), weekday):
            continue
        start_raw, end_raw = [chunk.strip() for chunk in time_range.split("-", 1)]
        start_minutes = _parse_minutes(start_raw)
        end_minutes = _parse_minutes(end_raw)
        if start_minutes is None or end_minutes is None:
            continue
        if start_minutes <= current_minutes <= end_minutes:
            direction = direction.strip()
            if direction in {"positive", "negative"}:
                return direction, 4.0
    return None, 0.0


def _matches_days(expression: str, weekday: int) -> bool:
    aliases = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    expr = expression.lower()
    if "-" in expr:
        start, end = [part.strip()[:3] for part in expr.split("-", 1)]
        if start not in aliases or end not in aliases:
            return False
        return aliases[start] <= weekday <= aliases[end]
    return aliases.get(expr[:3], -1) == weekday


def _parse_minutes(value: str) -> Optional[int]:
    try:
        hours, minutes = value.split(":", 1)
        return (int(hours) * 60) + int(minutes)
    except ValueError:
        return None
