from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite, sqrt
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class VolatilityForecast:
    dataset_hash: str
    observations: int
    horizon: int
    forecast: tuple[float, ...]


def forecast_volatility(returns: Iterable[float], *, horizon: int) -> VolatilityForecast:
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    data = np.asarray(list(returns), dtype=np.float64).reshape(-1)
    if data.size < 50:
        raise ValueError("at least 50 observations are required")
    if not np.isfinite(data).all():
        raise ValueError("returns must be finite")

    from arch import arch_model

    model = arch_model(data * 100.0, mean="Zero", vol="GARCH", p=1, q=1, rescale=False)
    fitted = model.fit(disp="off", show_warning=False)
    variances = np.asarray(
        fitted.forecast(horizon=horizon, reindex=False).variance.iloc[-1],
        dtype=float,
    ).reshape(-1)
    values = tuple(sqrt(max(float(value), 0.0)) / 100.0 for value in variances)
    if len(values) != horizon or not all(isfinite(value) and value > 0.0 for value in values):
        raise RuntimeError("volatility forecast must be positive and finite")
    return VolatilityForecast(
        dataset_hash=hashlib.sha256(data.tobytes()).hexdigest(),
        observations=int(data.size),
        horizon=int(horizon),
        forecast=values,
    )
