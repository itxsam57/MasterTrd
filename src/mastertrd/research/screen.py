from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from mastertrd.contracts import EvaluationResult, MarketBar
from mastertrd.execution_policy import PositionState, evaluate_execution_policy
from mastertrd.execution_signals import (
    SignalDirection,
    evaluate_multileg_signal,
)
from mastertrd.genome import StrategyGenome


def _finite(value: float, default: float = 0.0) -> float:
    result = float(value)
    return result if isfinite(result) else default


def _metrics(
    *,
    portfolio,
    strategy_id: str,
    genome_hash: str,
    dataset_hash: str,
    code_hash: str,
    engine_version: str,
    fees: float,
    slippage: float,
) -> EvaluationResult:
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
        strategy_id=strategy_id,
        genome_hash=genome_hash,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        engine="vectorbt",
        engine_version=engine_version,
        total_return=total_return,
        sharpe=_finite(sharpe),
        sortino=_finite(sortino),
        max_drawdown=max_drawdown,
        profit_factor=0.0,
        expectancy=_finite(expectancy),
        trade_count=trade_count,
        turnover=0.0,
        fees=float(fees),
        slippage=float(slippage),
        scores={"screen": 1.0 if total_return > 0 else 0.0},
    )


def _validate_bars(
    genome: StrategyGenome,
    bars_by_instrument: Mapping[str, Sequence[MarketBar]],
) -> dict[str, tuple[MarketBar, ...]]:
    missing = [instrument for instrument in genome.instruments if instrument not in bars_by_instrument]
    if missing:
        raise ValueError(f"missing instrument data for: {', '.join(missing)}")
    normalized: dict[str, tuple[MarketBar, ...]] = {}
    for instrument in genome.instruments:
        bars = tuple(bars_by_instrument[instrument])
        if len(bars) < 2:
            raise ValueError(f"instrument data is too short for {instrument}")
        if any(not isfinite(float(bar.close)) or float(bar.close) <= 0.0 for bar in bars):
            raise ValueError("bar prices must be positive and finite")
        normalized[instrument] = bars
    count = min(len(items) for items in normalized.values())
    if count < 2:
        raise ValueError("aligned instrument data is too short")
    return {key: value[-count:] for key, value in normalized.items()}


def _dataset_hash(bars_by_instrument: Mapping[str, Sequence[MarketBar]]) -> str:
    payload: list[dict[str, object]] = []
    for instrument in sorted(bars_by_instrument):
        for bar in bars_by_instrument[instrument]:
            payload.append(
                {
                    "instrument": instrument,
                    "timestamp": bar.timestamp.isoformat(),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                    "extras": dict(sorted(bar.extras.items())),
                }
            )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _synthetic_prices(
    genome: StrategyGenome,
    aligned: Mapping[str, Sequence[MarketBar]],
) -> pd.Series:
    if len(genome.instruments) == 1:
        bars = aligned[genome.instruments[0]]
        return pd.Series(
            [float(bar.close) for bar in bars],
            index=pd.DatetimeIndex([bar.timestamp for bar in bars]),
            dtype=float,
        )

    # Multi-leg VectorBT screening currently uses a normalized basket only as
    # the PnL price path. Task 2 replaces this approximation with per-leg
    # sizing and execution; leg direction still comes from shared semantics.
    first = aligned[genome.instruments[0]]
    matrix = np.asarray(
        [[float(bar.close) for bar in aligned[instrument]] for instrument in genome.instruments],
        dtype=float,
    )
    normalized = matrix / matrix[:, [0]]
    basket = normalized.mean(axis=0) * 100.0
    return pd.Series(
        basket,
        index=pd.DatetimeIndex([bar.timestamp for bar in first]),
        dtype=float,
    )


def _flat_state() -> PositionState:
    return PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)


def _opened_state(direction: SignalDirection, bar: MarketBar) -> PositionState:
    price = float(bar.close)
    return PositionState(direction, price, price, price, 0)


def _advance_state(position: PositionState, bar: MarketBar) -> PositionState:
    if position.direction is SignalDirection.FLAT:
        return position
    return PositionState(
        direction=position.direction,
        entry_price=position.entry_price,
        peak_price=max(position.peak_price, float(bar.high)),
        trough_price=min(position.trough_price, float(bar.low)),
        bars_held=position.bars_held + 1,
    )


def _single_leg_signals(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    count = len(bars)
    entries = np.zeros(count, dtype=bool)
    exits = np.zeros(count, dtype=bool)
    short_entries = np.zeros(count, dtype=bool)
    short_exits = np.zeros(count, dtype=bool)
    position = _flat_state()

    for index in range(count):
        current = bars[index]
        if position.direction is not SignalDirection.FLAT:
            position = _advance_state(position, current)
        decision = evaluate_execution_policy(genome, bars[: index + 1], position)

        if position.direction is SignalDirection.FLAT:
            if decision.direction is SignalDirection.LONG:
                entries[index] = True
                position = _opened_state(SignalDirection.LONG, current)
            elif decision.direction is SignalDirection.SHORT and genome.allow_short:
                short_entries[index] = True
                position = _opened_state(SignalDirection.SHORT, current)
            continue

        if not decision.close_position:
            continue

        if position.direction is SignalDirection.LONG:
            exits[index] = True
        else:
            short_exits[index] = True

        if decision.direction is SignalDirection.LONG:
            entries[index] = True
            position = _opened_state(SignalDirection.LONG, current)
        elif decision.direction is SignalDirection.SHORT and genome.allow_short:
            short_entries[index] = True
            position = _opened_state(SignalDirection.SHORT, current)
        else:
            position = _flat_state()

    return entries, exits, short_entries, short_exits


def _multi_leg_direction_signals(
    genome: StrategyGenome,
    aligned: Mapping[str, Sequence[MarketBar]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # This preserves the pre-V2 multi-leg screening behavior until Task 2
    # replaces basket approximation with real per-leg quantities and exits.
    count = len(next(iter(aligned.values())))
    directions: list[SignalDirection] = []
    for index in range(1, count + 1):
        decision = evaluate_multileg_signal(
            genome,
            {key: value[:index] for key, value in aligned.items()},
        )
        directions.append(decision.direction)

    entries = np.zeros(count, dtype=bool)
    exits = np.zeros(count, dtype=bool)
    short_entries = np.zeros(count, dtype=bool)
    short_exits = np.zeros(count, dtype=bool)
    previous = SignalDirection.FLAT
    for index, direction in enumerate(directions):
        if direction is SignalDirection.LONG and previous is not SignalDirection.LONG:
            if previous is SignalDirection.SHORT:
                short_exits[index] = True
            entries[index] = True
        elif direction is SignalDirection.SHORT and previous is not SignalDirection.SHORT:
            if previous is SignalDirection.LONG:
                exits[index] = True
            if genome.allow_short:
                short_entries[index] = True
        elif direction is SignalDirection.FLAT:
            if previous is SignalDirection.LONG:
                exits[index] = True
            elif previous is SignalDirection.SHORT:
                short_exits[index] = True
        previous = direction
    return entries, exits, short_entries, short_exits


def screen_genome(
    genome: StrategyGenome,
    bars_by_instrument: Mapping[str, Sequence[MarketBar]],
    *,
    fees: float,
    slippage: float,
) -> EvaluationResult:
    """Fast VectorBT screening using the same executable policy as execution."""
    if fees < 0.0 or slippage < 0.0:
        raise ValueError("fees and slippage cannot be negative")
    aligned = _validate_bars(genome, bars_by_instrument)

    if len(genome.instruments) == 1:
        entries, exits, short_entries, short_exits = _single_leg_signals(
            genome,
            aligned[genome.instruments[0]],
        )
    else:
        entries, exits, short_entries, short_exits = _multi_leg_direction_signals(genome, aligned)

    import vectorbt as vbt

    prices = _synthetic_prices(genome, aligned)
    portfolio = vbt.Portfolio.from_signals(
        prices,
        entries,
        exits,
        short_entries=short_entries,
        short_exits=short_exits,
        init_cash=10_000.0,
        fees=fees,
        slippage=slippage,
    )
    return _metrics(
        portfolio=portfolio,
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        dataset_hash=_dataset_hash(aligned),
        code_hash=hashlib.sha256(b"screen_genome:shared-execution-policy:v2").hexdigest(),
        engine_version=str(getattr(vbt, "__version__", "unknown")),
        fees=fees,
        slippage=slippage,
    )


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
    return _metrics(
        portfolio=portfolio,
        strategy_id=f"SCREEN-MA-{fast}-{slow}",
        genome_hash=genome_hash,
        dataset_hash=dataset_hash,
        code_hash=hashlib.sha256(b"moving_average_screen:v1").hexdigest(),
        engine_version=str(getattr(vbt, "__version__", "unknown")),
        fees=fees,
        slippage=0.0,
    )
