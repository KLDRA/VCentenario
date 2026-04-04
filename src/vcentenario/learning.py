from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


def classify_traffic_level(score: float) -> str:
    if score < 15:
        return "fluido"
    if score < 35:
        return "denso"
    if score < 60:
        return "retenciones"
    return "congestion_fuerte"


def local_slot_from_iso(timestamp: str, timezone_name: str) -> Tuple[int, int, str]:
    dt = datetime.fromisoformat(timestamp)
    local_dt = dt.astimezone(ZoneInfo(timezone_name))
    return local_dt.weekday(), local_dt.hour, local_dt.isoformat()


def next_local_slot(weekday: int, hour: int) -> Tuple[int, int]:
    hour += 1
    if hour >= 24:
        return (weekday + 1) % 7, 0
    return weekday, hour


def ema(previous_value: Optional[float], new_value: float, alpha: float) -> float:
    if previous_value is None:
        return new_value
    return (alpha * new_value) + ((1.0 - alpha) * previous_value)


def profile_confidence(sample_count: int) -> float:
    if sample_count <= 0:
        return 0.15
    return max(0.2, min(0.9, 0.2 + (sample_count / 24.0) * 0.5))


def build_forecast(
    reference_time: str,
    current_score: float,
    recent_states: Iterable[Dict[str, object]],
    profiles: Dict[Tuple[int, int], Dict[str, object]],
    timezone_name: str,
) -> Dict[str, object]:
    weekday, hour, local_time = local_slot_from_iso(reference_time, timezone_name)
    next_weekday, next_hour = next_local_slot(weekday, hour)
    current_profile = profiles.get((weekday, hour))
    next_profile = profiles.get((next_weekday, next_hour)) or current_profile

    recent_scores = [
        float(state.get("traffic_score", 0.0))
        for state in recent_states
        if state.get("traffic_score") is not None
    ]
    recent_scores = recent_scores[-6:]
    trend = 0.0
    if len(recent_scores) >= 2:
        trend = (recent_scores[-1] - recent_scores[0]) / max(len(recent_scores) - 1, 1)
        trend = max(-6.0, min(6.0, trend))

    baseline_now = float(current_profile["ema_score"]) if current_profile else current_score
    baseline_next = float(next_profile["ema_score"]) if next_profile else baseline_now
    predicted_score = max(0.0, round((baseline_next * 0.65) + (current_score * 0.25) + (trend * 0.10), 2))
    sample_count = int(next_profile["sample_count"]) if next_profile else 0
    confidence = round(profile_confidence(sample_count), 2)
    return {
        "slot_local_time": local_time,
        "slot_weekday": weekday,
        "slot_hour": hour,
        "baseline_score_now": round(baseline_now, 2),
        "baseline_score_next": round(baseline_next, 2),
        "predicted_score_next": predicted_score,
        "predicted_level_next": classify_traffic_level(predicted_score),
        "trend_score_per_run": round(trend, 2),
        "profile_samples_next": sample_count,
        "confidence": confidence,
    }
