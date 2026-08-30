from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class PortfolioStressEvidence:
    dataset_hash: str
    observations: int
    assets: tuple[str, ...]
    fold_count: int
    worst_fold_return: float
    mean_fold_return: float
    train_size: int
    test_size: int
    purged_size: int


def portfolio_stress(
    returns_frame,
    *,
    train_size: int,
    test_size: int,
    purged_size: int,
) -> PortfolioStressEvidence:
    if train_size <= 1 or test_size <= 0 or purged_size < 0:
        raise ValueError("invalid walk-forward sizes")
    frame = pd.DataFrame(returns_frame, dtype=float).copy()
    if frame.empty or frame.shape[1] < 2:
        raise ValueError("portfolio stress requires at least two assets")
    if len(frame) < train_size + test_size + purged_size:
        raise ValueError("insufficient observations for walk-forward stress")
    values = frame.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("portfolio returns must be finite")

    from skfolio.model_selection import WalkForward

    cv = WalkForward(train_size=train_size, test_size=test_size, purged_size=purged_size)
    fold_returns: list[float] = []
    for _train, test in cv.split(values):
        equal_weight = values[test].mean(axis=1)
        compounded = float(np.prod(1.0 + equal_weight) - 1.0)
        if not isfinite(compounded):
            raise RuntimeError("portfolio stress produced non-finite evidence")
        fold_returns.append(compounded)
    if not fold_returns:
        raise RuntimeError("walk-forward stress produced no folds")

    hash_payload = values.tobytes() + "|".join(map(str, frame.columns)).encode()
    return PortfolioStressEvidence(
        dataset_hash=hashlib.sha256(hash_payload).hexdigest(),
        observations=int(len(frame)),
        assets=tuple(str(column) for column in frame.columns),
        fold_count=len(fold_returns),
        worst_fold_return=float(min(fold_returns)),
        mean_fold_return=float(np.mean(fold_returns)),
        train_size=int(train_size),
        test_size=int(test_size),
        purged_size=int(purged_size),
    )
