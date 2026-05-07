from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import (
    REVERSIBLE_PERSISTENCE_WINDOW,
    REVERSIBLE_SCHEDULE,
    TOMTOM_CALIBRATED_FREE_FLOW,
    TOMTOM_DIRECTION_BASELINE_OFFSET as _CONFIG_BASELINE_OFFSET,
)
from .learning import MLPredictor
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

# Mensajes VMS permanentes por obras u otras causas estructurales que NO reflejan
# condiciones de tráfico en tiempo real. Se ignoran completamente en la inferencia.
PANEL_IGNORED_LEGEND_FRAGMENTS = {
    "VEHICULO 20T/HUELVA-MERID/POR A4 CADIZ",
}

# Tipos de incidencia estructurales/permanentes que no reflejan el estado real del tráfico.
# Se ignoran completamente (peso = 0), no solo reducidos al baseline.
INCIDENT_IGNORED_TYPES = {
    "weightRestrictionInOperation",  # Restricción de 20T — señal estática de obras
}

# Detector weights calibrated for realistic traffic classification:
# - LOW velocities (30-60 km/h) on a 60 km/h bridge = congestion, but not extreme
# - Weight reduced from 0.7 to 0.12 to prevent over-scoring (e.g., 30 km/h difference should contribute ~3.6 to score, not 21)
DETECTOR_FLOW_WEIGHT = 0.015
DETECTOR_OCCUPANCY_WEIGHT = 0.08  # Reduced from 0.35: occupancy alone shouldn't drive score
DETECTOR_SLOW_SPEED_WEIGHT = 0.12  # Reduced from 0.7: slower penalty, max ~7 per detector
DETECTOR_DIRECTION_BIAS_WEIGHT = 3.0  # Reduced from 10.0
PERSISTENT_BASELINE_SCALE = 0.15
CALIBRATION_EXCLUDED_SOURCES = {"camera_availability", "camera_change", "vehicle_count"}

# TomTom reversible inference thresholds
# Asimetría: diferencia de velocidad entre sentidos para inferir el reversible.
# Con radar de tramo en 60 km/h, el rango útil es estrecho (30–58 km/h).
# 8 km/h es conservador — se calibrará con datos reales de la semana.
TOMTOM_ASYMMETRY_THRESHOLD = 8.0    # km/h mínima diferencia para considerar asimetría real
TOMTOM_ASYMMETRY_MAX_WEIGHT = 8.0   # peso máximo por asimetría
# Salto de velocidad: subida repentina en un sentido indica apertura del reversible.
TOMTOM_JUMP_THRESHOLD = 7.0         # km/h de subida respecto a media reciente
TOMTOM_JUMP_MAX_WEIGHT = 5.0        # peso máximo por salto de velocidad
TOMTOM_HISTORY_WINDOW = 4           # número de lecturas recientes para calcular media (~20 min)
# Offset estructural TomTom: la ruta Huelva es sistemáticamente ~4 km/h más rápida
# que la Cádiz durante tráfico muerto (00–05h). No es el reversible, es el cálculo
# de TomTom (trazado, semáforos de acceso). Se resta a Huelva antes de medir asimetría.
# Calculado sobre 5 días de datos (abr 2026); ajustable vía env var.
TOMTOM_DIRECTION_BASELINE_OFFSET = _CONFIG_BASELINE_OFFSET  # km/h


def infer_bridge_state(
    panels: Iterable[PanelMessage],
    incidents: Iterable[Incident],
    snapshots: Iterable[CameraSnapshot],
    detectors: Iterable[DetectorReading] = (),
    recent_states: Optional[Sequence[Dict[str, object]]] = None,
    recent_detector_history: Optional[Sequence[Dict[str, object]]] = None,
    latest_report: Optional[Dict[str, object]] = None,
    recent_reports: Optional[Sequence[Dict[str, object]]] = None,
    observed_direction_profile: Optional[Dict[Tuple[int, int], Dict[str, object]]] = None,
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
        # Ignorar mensajes estáticos de obras u otras causas permanentes
        panel_text = " ".join(panel.legends).upper()
        if any(frag.upper() in panel_text for frag in PANEL_IGNORED_LEGEND_FRAGMENTS):
            continue
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
        if (incident.incident_type or "") in INCIDENT_IGNORED_TYPES:
            continue
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
                # Directional counts are still experimental for this camera, so
                # use only the coarse total as a weak occupancy hint.
                vehicle_total += snapshot.vehicle_count
        else:
            unavailable_cameras += 1
    if active_cameras:
        breakdown["camera_availability"] += min(active_cameras * 0.2, 1.0)
    if visual_change_total:
        breakdown["camera_change"] += min(visual_change_total, 1.0)
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

    tomtom_dir_pressure, tomtom_evidence = score_tomtom_reversible_signals(
        detectors, list(recent_detector_history or [])
    )
    for direction, weight in tomtom_dir_pressure.items():
        direction_pressure[direction] += weight
    evidence.extend(tomtom_evidence)

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
        latest_report=latest_report,
        recent_reports=recent_reports,
        observed_direction_profile=observed_direction_profile,
    )
    evidence.extend(direction_evidence)

    # ML Enhancement
    try:
        ml_predictor = MLPredictor(None)
        avg_speed_north = sum(d.average_speed or 0 for d in detectors if d.direction == 'north') / max(1, len([d for d in detectors if d.direction == 'north']))
        avg_speed_south = sum(d.average_speed or 0 for d in detectors if d.direction == 'south') / max(1, len([d for d in detectors if d.direction == 'south']))
        features = {
            'hour': datetime.now().hour,
            'avg_speed_north': avg_speed_north,
            'avg_speed_south': avg_speed_south,
            'incident_count': len(incidents),
            'panel_score': breakdown.get('panels', 0),
        }
        ml_traffic_level = ml_predictor.predict_traffic_level(features)
        ml_reversible_direction = ml_predictor.predict_reversible_direction(features)
        if ml_traffic_level != 'unknown':
            evidence.append(f"ml:traffic:{ml_traffic_level}")
        if ml_reversible_direction != 'indeterminado':
            evidence.append(f"ml:direction:{ml_reversible_direction}")
    except Exception as e:
        evidence.append(f"ml:error:{str(e)}")

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
    # Umbrales calibrados con datos reales del tramo SE-30 km 10-12:
    # velocidad máxima observada ~53 km/h, mínima ~5 km/h.
    # Distribución real (7 días, N=1140): p25=6.8 | p50=13.7 | p75=38.2 | p90=66.8 | p100=115
    if score < 8:
        return "fluido"           # ≥50 km/h aprox — muy fluido, circulación libre
    if score < 20:
        return "denso"            # 35–50 km/h aprox — fluido con tráfico notable
    if score < 42:
        return "retenciones"      # 20–35 km/h aprox — denso, velocidad reducida
    if score < 70:
        return "congestion_fuerte"  # 10–20 km/h aprox — retenciones importantes
    return "colapso"              # <10 km/h aprox — circulación muy lenta, colapso


def _report_age_seconds(reported_at: str) -> Optional[float]:
    """Devuelve los segundos transcurridos desde el reporte (UTC). None si no parseable."""
    try:
        dt = datetime.strptime(reported_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return None


def infer_reversible(
    direction_pressure: Dict[str, float],
    panels: List[PanelMessage],
    incidents: List[Incident],
    recent_states: Optional[Sequence[Dict[str, object]]] = None,
    persistence_window: int = 8,
    schedule: str = "",
    latest_report: Optional[Dict[str, object]] = None,
    recent_reports: Optional[Sequence[Dict[str, object]]] = None,
    observed_direction_profile: Optional[Dict[Tuple[int, int], Dict[str, object]]] = None,
) -> tuple[str, float, List[str]]:
    recent_states = list(recent_states or [])
    direction_pressure = defaultdict(float, direction_pressure)
    evidence: List[str] = []

    # — Señal de observación directa del usuario —
    # Si hay varios reportes recientes, agrupamos por dirección y sumamos pesos
    # con decaimiento por edad (14 si <15 min, 8 si <30 min, 4 si <60 min).
    # Para evitar abuso, capamos a 3 votos por dirección y a 50 puntos totales.
    # Si solo hay uno (o no se pasó la lista), comportamiento legacy con
    # latest_report.
    aggregated_reports = list(recent_reports or [])
    if not aggregated_reports and latest_report is not None:
        aggregated_reports = [latest_report]
    if aggregated_reports:
        votes: Dict[str, float] = defaultdict(float)
        counts: Dict[str, int] = defaultdict(int)
        most_recent_age: Dict[str, int] = {}
        for r in aggregated_reports:
            r_dir = str(r.get("direction", ""))
            age = _report_age_seconds(str(r.get("reported_at", "")))
            if age is None or age > 3600:
                continue
            if r_dir not in ("positive", "negative", "none"):
                continue
            # Cap por dirección: máximo 3 votos cuentan
            if counts[r_dir] >= 3:
                continue
            counts[r_dir] += 1
            if age <= 900:
                w = 14.0
            elif age <= 1800:
                w = 8.0
            else:
                w = 4.0
            votes[r_dir] += w
            if r_dir not in most_recent_age:
                most_recent_age[r_dir] = int(age // 60)
        # Capar totales (50 pts máx por dirección)
        for k in list(votes.keys()):
            votes[k] = min(votes[k], 50.0)
        # Aplicar el resultado del voto agregado
        winners = [d for d in ("positive", "negative") if votes[d] > 0]
        none_weight = votes.get("none", 0.0)
        # Si "none" gana (mayor peso que cualquier dirección), cancela presión
        if none_weight and (not winners or none_weight >= max(votes[d] for d in winners)):
            for k in list(direction_pressure.keys()):
                direction_pressure[k] *= 0.2
            evidence.append(f"reversible:user-reports:none:{counts['none']}votos:{none_weight:.0f}")
        else:
            for d in winners:
                direction_pressure[d] += votes[d]
                evidence.append(f"reversible:user-reports:{d}:{counts[d]}votos:{votes[d]:.0f}:{most_recent_age[d]}min")

    schedule_direction, schedule_weight = get_schedule_bias(schedule)
    if schedule_direction:
        direction_pressure[schedule_direction] += schedule_weight
        evidence.append(f"reversible:schedule:{schedule_direction}:{schedule_weight:.1f}")

    if observed_direction_profile:
        prior_dir, prior_weight, prior_ev = get_observed_hour_prior(observed_direction_profile)
        if prior_dir:
            direction_pressure[prior_dir] += prior_weight
            evidence.extend(prior_ev)

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


def score_tomtom_reversible_signals(
    detectors: Sequence[DetectorReading],
    recent_history: Sequence[Dict[str, object]],
) -> Tuple[Dict[str, float], List[str]]:
    """
    Two complementary signals from TomTom Routing speed data:

    1. Asymmetry — if one direction is significantly faster than the other,
       the SLOWER direction gets extra pressure (demand signal: congestion
       suggests the reversible is needed or open for that direction).

    2. Speed jump — a sudden speed increase in one direction vs. its recent
       average suggests the reversible just opened for it (supply signal:
       more lane capacity → speed recovered).
    """
    dir_pressure: Dict[str, float] = defaultdict(float)
    evidence: List[str] = []

    # Extract current speeds from TomTom route detectors
    current_speeds: Dict[str, float] = {}
    for d in detectors:
        if d.source != "tomtom" or d.average_speed is None:
            continue
        det_id = (d.detector_id or "").lower()
        if det_id.endswith("_huelva"):
            current_speeds["positive"] = d.average_speed
        elif det_id.endswith("_cadiz"):
            current_speeds["negative"] = d.average_speed

    if len(current_speeds) < 2:
        return {}, []

    speed_pos = current_speeds["positive"]
    speed_neg = current_speeds["negative"]

    # — Asymmetry signal —
    # Corregimos el offset estructural de ~4 km/h a favor de Huelva observado
    # en tráfico muerto. Sin esta corrección (positive - negative) tiene un sesgo
    # fijo +4 que enmascara la asimetría real del reversible.
    diff = (speed_pos - TOMTOM_DIRECTION_BASELINE_OFFSET) - speed_neg
    abs_diff = abs(diff)
    if abs_diff >= TOMTOM_ASYMMETRY_THRESHOLD:
        slower_dir = "negative" if diff > 0 else "positive"
        # Escala lineal más allá del umbral, cap en el máximo configurado
        weight = min(
            TOMTOM_ASYMMETRY_MAX_WEIGHT * abs_diff / max(TOMTOM_ASYMMETRY_THRESHOLD * 2, 1.0),
            TOMTOM_ASYMMETRY_MAX_WEIGHT,
        )
        dir_pressure[slower_dir] += round(weight, 2)
        evidence.append(
            f"tomtom:asymmetry:{slower_dir}:{abs_diff:.1f}kmh(corr):{weight:.1f}"
        )

    # — Speed jump signal —
    if recent_history:
        history_speeds: Dict[str, List[float]] = defaultdict(list)
        for row in recent_history:
            dir_ = str(row.get("direction") or "")
            spd = row.get("average_speed")
            if dir_ in ("positive", "negative") and spd is not None:
                history_speeds[dir_].append(float(spd))

        for dir_, hist in history_speeds.items():
            current_spd = current_speeds.get(dir_)
            if current_spd is None or len(hist) < 2:
                continue
            window = hist[-TOMTOM_HISTORY_WINDOW:]
            recent_avg = sum(window) / len(window)
            jump = current_spd - recent_avg
            if jump >= TOMTOM_JUMP_THRESHOLD:
                weight = min(
                    TOMTOM_JUMP_MAX_WEIGHT * jump / max(TOMTOM_JUMP_THRESHOLD * 2, 1.0),
                    TOMTOM_JUMP_MAX_WEIGHT,
                )
                dir_pressure[dir_] += round(weight, 2)
                evidence.append(f"tomtom:jump:{dir_}:+{jump:.1f}kmh:{weight:.1f}")

    return dict(dir_pressure), evidence


def score_detectors(detectors: Sequence[DetectorReading]) -> Tuple[float, List[str], Dict[str, float]]:
    if not detectors:
        return 0.0, [], {}
    local_scores: List[float] = []
    dir_local: List[Tuple[str, float]] = []
    evidence: List[str] = []
    direction_pressure: Dict[str, float] = defaultdict(float)

    for detector in detectors:
        if detector.average_speed is None and detector.vehicle_flow is None and detector.occupancy is None:
            continue
        local_score = 0.0

        # Velocidad: indicador principal de congestión.
        # SE-30 km 10–12 tiene límite de 60 km/h en ambos sentidos.
        if detector.source == "tomtom":
            slow_threshold = TOMTOM_CALIBRATED_FREE_FLOW  # ya calibrado a 60.0
        else:
            slow_threshold = 60.0

        if detector.average_speed is not None and detector.average_speed < slow_threshold:
            local_score += min((slow_threshold - detector.average_speed) * DETECTOR_SLOW_SPEED_WEIGHT, 7.0)

        # Ocupación: buen proxy de densidad cuando está disponible (principalmente DGT).
        if detector.occupancy is not None:
            local_score += min(detector.occupancy * DETECTOR_OCCUPANCY_WEIGHT, 4.0)

        # Flujo vehicular: solo para TomTom (no da speed+flow simultáneamente).
        # Para DGT se omite: en vías de varios carriles el flujo siempre es alto y
        # no discrimina entre tráfico fluido y congestionado.
        if detector.source == "tomtom" and detector.vehicle_flow is not None:
            local_score += min(detector.vehicle_flow * DETECTOR_FLOW_WEIGHT, 10.0)

        local_scores.append(local_score)

        # Determinar dirección desde el campo o desde el nombre del detector (TomTom).
        direction = detector.direction
        if not direction and detector.source == "tomtom":
            det_id_lower = (detector.detector_id or "").lower()
            if det_id_lower.endswith("_positivo") or det_id_lower.endswith("_huelva"):
                direction = "positive"
            elif det_id_lower.endswith("_negativo") or det_id_lower.endswith("_cadiz"):
                direction = "negative"

        if direction:
            dir_local.append((direction, local_score))

    active_count = len(local_scores)
    if not active_count:
        return 0.0, [], {}

    # Normalizar: media por sensor para que el score sea independiente del número de detectores.
    avg_score = sum(local_scores) / active_count
    score = round(avg_score * active_count ** 0.5, 2)  # escala suave: √n en lugar de n

    # direction_pressure: media por dirección para el cálculo del carril reversible.
    dir_totals: Dict[str, List[float]] = defaultdict(list)
    for d, s in dir_local:
        dir_totals[d].append(s)
    for d, scores in dir_totals.items():
        direction_pressure[d] = min(sum(scores) / len(scores), DETECTOR_DIRECTION_BIAS_WEIGHT)

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
        or "RESTRICCION" in text  # Weight restrictions
        or "roadworks" in panel.pictograms
        or is_informational_bridge_panel
    )
    if not looks_permanent:
        return False
    # For operational/permanent infrastructure messages, reduce score immediately without waiting for history
    return True


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
    # For operational/permanent infrastructure incidents, reduce score immediately without waiting for history
    return True


def evidence_seen_frequently(evidence_key: str, recent_states: Sequence[Dict[str, object]], threshold: int = 2) -> bool:
    # Threshold reduced from 4 to 2 to detect persistent operational events faster
    # (especially after DB cleanup or service restart)
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
        return 0.5
    if vehicle_count <= 6:
        return 0.75
    if vehicle_count <= 8:
        return 1.25
    if vehicle_count <= 12:
        return 2.0
    if vehicle_count <= 16:
        return 3.0
    return 4.0


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


def get_observed_hour_prior(
    profile: Dict[Tuple[int, int], Dict[str, object]],
) -> Tuple[Optional[str], float, List[str]]:
    """Prior observado por slot (weekday, hour) a partir de la asimetría corregida
    histórica. Peso bajo (hasta 3.0) porque es una señal estadística de fondo,
    no una observación en tiempo real. Usa hora LOCAL, asumiendo Europe/Madrid
    (UTC+2 en horario de verano)."""
    now = datetime.now()
    slot = (now.weekday(), now.hour)
    entry = profile.get(slot)
    if not entry:
        return None, 0.0, []
    direction = str(entry.get("direction", ""))
    if direction not in ("positive", "negative"):
        return None, 0.0, []
    abs_diff = float(entry.get("abs_diff", 0.0) or 0.0)
    samples = int(entry.get("sample_count", 0) or 0)
    if samples < 3 or abs_diff < 1.0:
        return None, 0.0, []
    # Escalado: 1 km/h → 1 pt, 4 km/h → 3 pt, cap 3.0. Peso intencionalmente bajo.
    weight = round(min(abs_diff * 0.75, 3.0), 2)
    return direction, weight, [
        f"reversible:hour-prior:{direction}:{abs_diff:.1f}kmh(n={samples}):{weight:.1f}"
    ]


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
