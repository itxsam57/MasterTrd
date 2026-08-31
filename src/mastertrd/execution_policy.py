from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from statistics import fmean
from typing import Mapping, Sequence

from .contracts import MarketBar
from .execution_signals import SignalDirection, atr, evaluate_bar_signal
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
    legs: Mapping[str, int] = field(default_factory=dict)


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
        # If both levels are touched by one OHLC bar, choose the adverse fill.
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
    raise ValueError(f"unsupported exit policy: {kind}")
