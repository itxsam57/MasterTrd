from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from statistics import fmean
from typing import Mapping, Sequence

from .contracts import MarketBar
from .execution_signals import (
    SignalDirection,
    atr,
    evaluate_bar_signal,
    evaluate_multileg_signal,
    zscore,
)
from .genome import StrategyGenome


@dataclass(frozen=True, slots=True)
class PositionState:
    direction: SignalDirection
    entry_price: float
    peak_price: float
    trough_price: float
    bars_held: int

    def __post_init__(self) -> None:
        prices = (self.entry_price, self.peak_price, self.trough_price)
        if not all(isfinite(float(value)) and float(value) >= 0.0 for value in prices):
            raise ValueError("position prices must be finite and non-negative")
        if self.direction is not SignalDirection.FLAT and self.entry_price <= 0.0:
            raise ValueError("open positions require a positive entry_price")
        if self.bars_held < 0:
            raise ValueError("bars_held cannot be negative")
        if self.direction is not SignalDirection.FLAT:
            if self.peak_price < self.trough_price:
                raise ValueError("peak_price cannot be below trough_price")
            if not self.trough_price <= self.entry_price <= self.peak_price:
                raise ValueError("entry_price must be inside the observed position range")


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    direction: SignalDirection
    reason: str
    close_position: bool = False
    legs: Mapping[str, float] = field(default_factory=dict)
    rebalance_position: bool = False


def _exit_kind(genome: StrategyGenome) -> str:
    value = genome.exit.get("kind", genome.exit.get("type"))
    if not value:
        raise ValueError("strategy exit policy is required")
    return str(value)


def _hold(position: PositionState, reason: str) -> ExecutionDecision:
    return ExecutionDecision(position.direction, reason, False)


def _flat(reason: str) -> ExecutionDecision:
    return ExecutionDecision(SignalDirection.FLAT, reason, True)


def _previous_atr(bars: Sequence[MarketBar], period: int) -> float | None:
    if period <= 0:
        raise ValueError("atr_period must be positive")
    history = tuple(bars[:-1])
    if len(history) <= period:
        return None
    return float(atr(history, period))


def _atr_bracket(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    stop_multiple = float(genome.exit["stop_atr"])
    target_multiple = float(genome.exit["target_atr"])
    period = int(genome.exit.get("atr_period", 14))
    if stop_multiple <= 0.0 or target_multiple <= 0.0:
        raise ValueError("ATR bracket multiples must be positive")
    volatility = _previous_atr(bars, period)
    if volatility is None:
        return _hold(position, "atr_exit_warmup")

    current = bars[-1]
    if position.direction is SignalDirection.LONG:
        stop_price = position.entry_price - stop_multiple * volatility
        target_price = position.entry_price + target_multiple * volatility
        if float(current.low) <= stop_price:
            return _flat("atr_stop")
        if float(current.high) >= target_price:
            return _flat("atr_target")
        return _hold(position, "hold_atr_bracket")

    if position.direction is SignalDirection.SHORT:
        stop_price = position.entry_price + stop_multiple * volatility
        target_price = position.entry_price - target_multiple * volatility
        if float(current.high) >= stop_price:
            return _flat("atr_stop")
        if float(current.low) <= target_price:
            return _flat("atr_target")
        return _hold(position, "hold_atr_bracket")

    return ExecutionDecision(SignalDirection.FLAT, "flat", False)


def _trailing_atr(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    multiple = float(genome.exit["atr"])
    period = int(genome.exit.get("atr_period", 14))
    if multiple <= 0.0:
        raise ValueError("trailing ATR multiple must be positive")
    volatility = _previous_atr(bars, period)
    if volatility is None:
        return _hold(position, "trailing_atr_warmup")

    current = bars[-1]
    if position.direction is SignalDirection.LONG:
        trailing_stop = position.peak_price - multiple * volatility
        if float(current.low) <= trailing_stop:
            return _flat("trailing_atr")
        return _hold(position, "hold_trailing_atr")
    if position.direction is SignalDirection.SHORT:
        trailing_stop = position.trough_price + multiple * volatility
        if float(current.high) >= trailing_stop:
            return _flat("trailing_atr")
        return _hold(position, "hold_trailing_atr")
    return ExecutionDecision(SignalDirection.FLAT, "flat", False)


def _mean_or_atr_stop(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    window = int(genome.entry.get("window", 0))
    stop_multiple = float(genome.exit["stop_atr"])
    period = int(genome.exit.get("atr_period", 14))
    if window < 2 or stop_multiple <= 0.0:
        raise ValueError("mean/ATR exit requires a valid window and positive stop_atr")
    if len(bars) <= window:
        return _hold(position, "mean_exit_warmup")

    current = bars[-1]
    history = [float(bar.close) for bar in bars[-window - 1 : -1]]
    mean_price = fmean(history)
    volatility = _previous_atr(bars, period)

    if position.direction is SignalDirection.LONG:
        if float(current.close) >= mean_price:
            return _flat("mean_reversion_exit")
        if volatility is not None and float(current.low) <= position.entry_price - stop_multiple * volatility:
            return _flat("atr_stop")
        return _hold(position, "hold_mean_or_atr_stop")
    if position.direction is SignalDirection.SHORT:
        if float(current.close) <= mean_price:
            return _flat("mean_reversion_exit")
        if volatility is not None and float(current.high) >= position.entry_price + stop_multiple * volatility:
            return _flat("atr_stop")
        return _hold(position, "hold_mean_or_atr_stop")
    return ExecutionDecision(SignalDirection.FLAT, "flat", False)


def _cross_reverse(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    signal = evaluate_bar_signal(genome, bars)
    if signal.direction is SignalDirection.FLAT or signal.direction is position.direction:
        return _hold(position, "hold_cross_reverse")
    if signal.direction is SignalDirection.SHORT and not genome.allow_short:
        return _flat("cross_reverse")
    return ExecutionDecision(signal.direction, "cross_reverse", True, signal.legs)


def _greeks_or_time_exit(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    max_days = float(genome.exit["max_days"])
    if not isfinite(max_days) or max_days < 0.0:
        raise ValueError("greeks_or_time_exit max_days must be finite and non-negative")
    days_to_expiry = bars[-1].extras.get("days_to_expiry")
    if days_to_expiry is None:
        raise ValueError("greeks_or_time_exit requires days_to_expiry option state")
    observed_days = float(days_to_expiry)
    if not isfinite(observed_days) or observed_days < 0.0:
        raise ValueError("days_to_expiry must be finite and non-negative")
    if observed_days <= max_days:
        return _flat("option_time_exit")
    return _hold(position, "hold_greeks_or_time_exit")


def evaluate_execution_policy(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    if not bars:
        raise ValueError("market bars are required")

    if position.direction is SignalDirection.FLAT:
        signal = evaluate_bar_signal(genome, bars)
        return ExecutionDecision(signal.direction, signal.reason, False, signal.legs)

    kind = _exit_kind(genome)
    if kind == "cross_reverse":
        return _cross_reverse(genome, bars, position)
    if kind == "atr_bracket":
        return _atr_bracket(genome, bars, position)
    if kind == "mean_or_atr_stop":
        return _mean_or_atr_stop(genome, bars, position)
    if kind == "trailing_atr":
        return _trailing_atr(genome, bars, position)
    if kind == "greeks_or_time_exit":
        return _greeks_or_time_exit(genome, bars, position)
    raise ValueError(f"unsupported exit policy: {kind}")


def _aligned_multileg_bars(
    genome: StrategyGenome,
    bars_by_instrument: Mapping[str, Sequence[MarketBar]],
) -> dict[str, tuple[MarketBar, ...]]:
    missing = [instrument for instrument in genome.instruments if instrument not in bars_by_instrument]
    if missing:
        raise ValueError(f"missing multi-leg bars for: {', '.join(missing)}")
    normalized = {instrument: tuple(bars_by_instrument[instrument]) for instrument in genome.instruments}
    if any(not bars for bars in normalized.values()):
        raise ValueError("multi-leg exit policy requires market bars for every instrument")
    count = min(len(bars) for bars in normalized.values())
    return {instrument: bars[-count:] for instrument, bars in normalized.items()}


def _float_legs(legs: Mapping[str, float]) -> dict[str, float]:
    return {str(instrument): float(weight) for instrument, weight in legs.items()}


def _zero_legs(genome: StrategyGenome) -> dict[str, float]:
    return {instrument: 0.0 for instrument in genome.instruments}


def _direction_from_legs(genome: StrategyGenome, legs: Mapping[str, float]) -> SignalDirection:
    first = float(legs.get(genome.instruments[0], 0.0))
    if first > 0.0:
        return SignalDirection.LONG
    if first < 0.0:
        return SignalDirection.SHORT
    return SignalDirection.FLAT


def _hold_multileg(
    genome: StrategyGenome,
    current_legs: Mapping[str, float],
    reason: str,
) -> ExecutionDecision:
    legs = _float_legs(current_legs)
    return ExecutionDecision(_direction_from_legs(genome, legs), reason, False, legs)


def _close_multileg(genome: StrategyGenome, reason: str) -> ExecutionDecision:
    return ExecutionDecision(SignalDirection.FLAT, reason, True, _zero_legs(genome))


def _funding_edge_bps(
    genome: StrategyGenome,
    aligned: Mapping[str, Sequence[MarketBar]],
) -> float:
    left = aligned[genome.instruments[0]][-1]
    right = aligned[genome.instruments[1]][-1]
    explicit = left.extras.get("basis_bps")
    if explicit is not None:
        return float(explicit)
    left_rate = left.extras.get("funding_rate")
    right_rate = right.extras.get("funding_rate")
    if left_rate is None or right_rate is None:
        raise ValueError("edge_decay requires basis_bps or funding_rate on both legs")
    return (float(left_rate) - float(right_rate)) * 10_000.0


def evaluate_multileg_execution_policy(
    genome: StrategyGenome,
    bars_by_instrument: Mapping[str, Sequence[MarketBar]],
    *,
    current_legs: Mapping[str, float],
    bars_held: int,
) -> ExecutionDecision:
    if len(genome.instruments) < 2:
        raise ValueError("multi-leg execution policy requires at least two instruments")
    if bars_held < 0:
        raise ValueError("bars_held cannot be negative")
    if set(current_legs) != set(genome.instruments):
        raise ValueError("current_legs must match the strategy instrument set exactly")
    open_legs = _float_legs(current_legs)
    if any(not isfinite(weight) for weight in open_legs.values()):
        raise ValueError("current_legs weights must be finite")

    aligned = _aligned_multileg_bars(genome, bars_by_instrument)
    is_open = any(abs(weight) > 0.0 for weight in open_legs.values())

    if not is_open:
        signal = evaluate_multileg_signal(genome, aligned)
        return ExecutionDecision(
            signal.direction,
            signal.reason,
            False,
            _float_legs(signal.legs),
        )

    kind = _exit_kind(genome)
    if kind == "spread_mean_exit":
        window = int(genome.entry.get("window", 0))
        exit_z = float(genome.exit["z_exit"])
        if window < 2 or exit_z < 0.0:
            raise ValueError("spread mean exit requires window >= 2 and z_exit >= 0")
        left = aligned[genome.instruments[0]]
        right = aligned[genome.instruments[1]]
        count = min(len(left), len(right))
        if count <= window:
            return _hold_multileg(genome, open_legs, "spread_exit_warmup")
        spreads = [float(left[index].close) - float(right[index].close) for index in range(count)]
        current_z = zscore(spreads[-1], spreads[-window - 1 : -1])
        if abs(current_z) <= exit_z:
            return _close_multileg(genome, "spread_mean_exit")
        return _hold_multileg(genome, open_legs, "hold_spread_mean_exit")

    if kind == "edge_decay":
        exit_bps = float(genome.exit["exit_bps"])
        if exit_bps < 0.0:
            raise ValueError("edge_decay exit_bps cannot be negative")
        edge_bps = _funding_edge_bps(genome, aligned)
        if abs(edge_bps) <= exit_bps:
            return _close_multileg(genome, "edge_decay")
        return _hold_multileg(genome, open_legs, "hold_edge_decay")

    if kind == "rebalance":
        if "drift_bps" in genome.exit:
            threshold = float(genome.exit["drift_bps"])
            if threshold <= 0.0:
                raise ValueError("rebalance drift_bps must be positive")
            latest = aligned[genome.instruments[0]][-1]
            observed = latest.extras.get("hedge_drift_bps")
            if observed is None:
                raise ValueError("rebalance requires hedge_drift_bps market state")
            if abs(float(observed)) < threshold:
                return _hold_multileg(genome, open_legs, "hold_rebalance")
        elif "periods" in genome.exit:
            periods = int(genome.exit["periods"])
            if periods <= 0:
                raise ValueError("rebalance periods must be positive")
            if bars_held == 0 or bars_held % periods != 0:
                return _hold_multileg(genome, open_legs, "hold_rebalance")
        else:
            raise ValueError("rebalance requires drift_bps or periods")

        signal = evaluate_multileg_signal(genome, aligned)
        return ExecutionDecision(
            signal.direction,
            "rebalance",
            False,
            _float_legs(signal.legs),
            True,
        )

    raise ValueError(f"unsupported multi-leg exit policy: {kind}")
