from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class IndependentReport:
    dataset_hash: str
    observations: int
    periods: int
    sharpe: float
    sortino: float
    max_drawdown: float
    compounded_return: float


def build_independent_report(returns: Iterable[float], *, periods: int) -> IndependentReport:
    if periods <= 0:
        raise ValueError("periods must be positive")
    data = np.asarray(list(returns), dtype=np.float64).reshape(-1)
    if data.size < 3:
        raise ValueError("at least three observations are required")
    if not np.isfinite(data).all():
        raise ValueError("returns must be finite")

    import quantstats as qs

    series = pd.Series(data, index=pd.date_range("2000-01-01", periods=len(data), freq="D"))
    sharpe = float(qs.stats.sharpe(series, periods=periods))
    sortino = float(qs.stats.sortino(series, periods=periods))
    max_drawdown = float(qs.stats.max_drawdown(series))
    compounded = float(qs.stats.comp(series))
    metrics = (sharpe, sortino, max_drawdown, compounded)
    if not all(isfinite(value) for value in metrics):
        raise RuntimeError("independent report produced non-finite metrics")
    return IndependentReport(
        dataset_hash=hashlib.sha256(data.tobytes()).hexdigest(),
        observations=int(data.size),
        periods=int(periods),
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        compounded_return=compounded,
    )
