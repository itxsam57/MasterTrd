from __future__ import annotations

import hashlib
import json
from math import isfinite

import numpy as np
import pandas as pd

from mastertrd.contracts import EvaluationResult


def _finite(value: float, default: float = 0.0) -> float:
    result = float(value)
    return result if isfinite(result) else default


def moving_average_screen(
    prices: pd.Series,
    *,
    fast: int,
    slow: int,
    fees: float = 0.0,
) -> EvaluationResult:
    if fast <= 0 or slow <= 0 or fast >= slow:
        raise ValueError("moving-average windows must satisfy 0 < fast < slow")
    if fees < 0:
        raise ValueError("fees cannot be negative")
    series = pd.Series(prices, dtype=float).dropna()
    if len(series) <= slow:
        raise ValueError("price history must be longer than slow window")
    if not np.isfinite(series.to_numpy()).all() or (series <= 0).any():
        raise ValueError("prices must be positive and finite")

    import vectorbt as vbt

    fast_ma = vbt.MA.run(series, window=fast).ma
    slow_ma = vbt.MA.run(series, window=slow).ma
    entries = fast_ma.vbt.crossed_above(slow_ma)
    exits = fast_ma.vbt.crossed_below(slow_ma)
    portfolio = vbt.Portfolio.from_signals(series, entries, exits, init_cash=10_000.0, fees=fees)

    params = json.dumps({"fast": fast, "slow": slow, "fees": fees}, sort_keys=True).encode()
    dataset_hash = hashlib.sha256(np.asarray(series, dtype=np.float64).tobytes()).hexdigest()
    genome_hash = hashlib.sha256(params).hexdigest()
    trade_count = int(portfolio.trades.count())
    total_return = _finite(portfolio.total_return())
    max_drawdown = abs(_finite(portfolio.max_drawdown()))

    returns = np.asarray(portfolio.returns(), dtype=float)
    finite_returns = returns[np.isfinite(returns)]
    mean_return = float(finite_returns.mean()) if finite_returns.size else 0.0
    std_return = float(finite_returns.std(ddof=1)) if finite_returns.size > 1 else 0.0
    downside = finite_returns[finite_returns < 0]
    downside_std = float(downside.std(ddof=1)) if downside.size > 1 else 0.0
    sharpe = mean_return / std_return if std_return > 0 else 0.0
    sortino = mean_return / downside_std if downside_std > 0 else 0.0
    expectancy = total_return / trade_count if trade_count else 0.0

    return EvaluationResult(
        strategy_id=f"SCREEN-MA-{fast}-{slow}",
        genome_hash=genome_hash,
        dataset_hash=dataset_hash,
        code_hash=hashlib.sha256(b"moving_average_screen:v1").hexdigest(),
        engine="vectorbt",
        engine_version=str(getattr(vbt, "__version__", "unknown")),
        total_return=total_return,
        sharpe=_finite(sharpe),
        sortino=_finite(sortino),
        max_drawdown=max_drawdown,
        profit_factor=0.0,
        expectancy=_finite(expectancy),
        trade_count=trade_count,
        turnover=0.0,
        fees=float(fees),
        slippage=0.0,
        scores={"screen": 1.0 if total_return > 0 else 0.0},
    )
