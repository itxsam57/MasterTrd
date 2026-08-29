from __future__ import annotations

from math import sqrt
from typing import Iterable

import numpy as np


def _finite_vector(values: Iterable[float], *, minimum: int = 3) -> np.ndarray:
    data = np.asarray(list(values), dtype=float).reshape(-1)
    if data.size < minimum:
        raise ValueError(f"at least {minimum} observations are required")
    if not np.isfinite(data).all():
        raise ValueError("observations must be finite")
    return data


def detect_change_points(values: Iterable[float], *, penalty: float) -> list[int]:
    if penalty <= 0:
        raise ValueError("penalty must be positive")
    data = _finite_vector(values, minimum=8)
    import ruptures as rpt

    points = rpt.Pelt(model="l2", min_size=3, jump=1).fit(data.reshape(-1, 1)).predict(pen=penalty)
    return [int(point) for point in points if point < len(data)]


def cointegration_pvalue(x: Iterable[float], y: Iterable[float]) -> float:
    x_data = _finite_vector(x, minimum=20)
    y_data = _finite_vector(y, minimum=20)
    if x_data.size != y_data.size:
        raise ValueError("series must have the same length")
    from statsmodels.tsa.stattools import coint

    _stat, pvalue, _critical = coint(x_data, y_data)
    if not np.isfinite(pvalue):
        raise RuntimeError("cointegration test produced a non-finite p-value")
    return float(pvalue)


def forecast_volatility(returns: Iterable[float]) -> float:
    data = _finite_vector(returns, minimum=50)
    from arch import arch_model

    # Fit in percentage units for numerical stability, then convert back.
    model = arch_model(data * 100.0, mean="Zero", vol="GARCH", p=1, q=1, rescale=False)
    fitted = model.fit(disp="off", show_warning=False)
    variance = float(fitted.forecast(horizon=1, reindex=False).variance.iloc[-1, 0])
    volatility = sqrt(max(variance, 0.0)) / 100.0
    if not np.isfinite(volatility) or volatility <= 0:
        raise RuntimeError("volatility forecast must be positive and finite")
    return volatility
