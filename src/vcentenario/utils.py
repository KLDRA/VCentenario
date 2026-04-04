from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def km_from_meters(value: Optional[str]) -> Optional[float]:
    meters = parse_float(value)
    if meters is None:
        return None
    return meters / 1000.0


def within_bbox(lat: Optional[float], lon: Optional[float], bbox: Tuple[float, float, float, float]) -> bool:
    if lat is None or lon is None:
        return False
    lat_min, lat_max, lon_min, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def km_in_range(km: Optional[float], km_min: float, km_max: float, margin: float = 0.0) -> bool:
    if km is None:
        return False
    return (km_min - margin) <= km <= (km_max + margin)


def overlap_range(
    start_a: Optional[float],
    end_a: Optional[float],
    start_b: float,
    end_b: float,
    margin: float = 0.0,
) -> bool:
    if start_a is None and end_a is None:
        return False
    lo = min(v for v in (start_a, end_a) if v is not None)
    hi = max(v for v in (start_a, end_a) if v is not None)
    return hi >= (start_b - margin) and lo <= (end_b + margin)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sampled_byte_change_ratio(previous: bytes, current: bytes, samples: int = 2048) -> float:
    if not previous or not current:
        return 1.0
    size = min(len(previous), len(current))
    if size == 0:
        return 1.0
    step = max(size // samples, 1)
    changed = 0
    total = 0
    for index in range(0, size, step):
        total += 1
        if previous[index] != current[index]:
            changed += 1
    if total == 0:
        return 1.0
    return changed / total


def dumps_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def text_join(values: Sequence[str], sep: str = " | ") -> str:
    return sep.join(v for v in values if v)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def configure_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
