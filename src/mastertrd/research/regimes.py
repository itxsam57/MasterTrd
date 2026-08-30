from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class RegimeMap:
    dataset_hash: str
    observations: int
    change_points: tuple[int, ...]
    min_size: int
    penalty: float


def _values(values: Iterable[float], *, minimum: int) -> np.ndarray:
    data = np.asarray(list(values), dtype=np.float64).reshape(-1)
    if data.size < minimum:
        raise ValueError(f"at least {minimum} observations are required")
    if not np.isfinite(data).all():
        raise ValueError("returns must be finite")
    return data


def discover_regimes(returns: Iterable[float], *, min_size: int, penalty: float) -> RegimeMap:
    if min_size < 2:
        raise ValueError("min_size must be at least two")
    if not isfinite(float(penalty)) or penalty <= 0.0:
        raise ValueError("penalty must be positive and finite")
    data = _values(returns, minimum=max(8, min_size * 2))

    import ruptures as rpt

    points = rpt.Pelt(model="l2", min_size=min_size, jump=1).fit(data.reshape(-1, 1)).predict(pen=penalty)
    change_points = tuple(int(point) for point in points if 0 < int(point) < len(data))
    return RegimeMap(
        dataset_hash=hashlib.sha256(data.tobytes()).hexdigest(),
        observations=int(data.size),
        change_points=change_points,
        min_size=int(min_size),
        penalty=float(penalty),
    )
