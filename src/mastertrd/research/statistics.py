from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite
from typing import Iterable

import numpy as np


@dataclass(frozen=True, slots=True)
class StatisticalEvidence:
    dataset_hash: str
    observations: int
    statistic: float
    pvalue: float
    max_pvalue: float
    passed: bool


def cointegration_evidence(
    left: Iterable[float],
    right: Iterable[float],
    *,
    max_pvalue: float,
) -> StatisticalEvidence:
    if not isfinite(float(max_pvalue)) or not 0.0 < max_pvalue <= 1.0:
        raise ValueError("max_pvalue must be within (0, 1]")
    left_data = np.asarray(list(left), dtype=np.float64).reshape(-1)
    right_data = np.asarray(list(right), dtype=np.float64).reshape(-1)
    if left_data.size < 20 or right_data.size < 20:
        raise ValueError("at least 20 paired observations are required")
    if left_data.size != right_data.size:
        raise ValueError("series must have the same length")
    if not np.isfinite(left_data).all() or not np.isfinite(right_data).all():
        raise ValueError("series must be finite")

    from statsmodels.tsa.stattools import coint

    statistic, pvalue, _critical = coint(left_data, right_data)
    if not isfinite(float(statistic)) or not isfinite(float(pvalue)):
        raise RuntimeError("cointegration test produced non-finite evidence")
    payload = np.column_stack((left_data, right_data)).astype(np.float64, copy=False)
    return StatisticalEvidence(
        dataset_hash=hashlib.sha256(payload.tobytes()).hexdigest(),
        observations=int(left_data.size),
        statistic=float(statistic),
        pvalue=float(pvalue),
        max_pvalue=float(max_pvalue),
        passed=bool(float(pvalue) <= float(max_pvalue)),
    )
