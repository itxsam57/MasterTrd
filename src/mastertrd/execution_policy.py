from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
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
class HftPositionState:
    direction: SignalDirection
    entry_price: float
    current_price: float
    tick_size: float
    ticks_held: int
    inventory: float
    imbalance: float
    spread_bps: float

    def __post_init__(self) -> None:
        for name in ("entry_price", "current_price", "tick_size"):
            value = float(getattr(self, name))
            if not isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be positive and finite")
        if self.ticks_held < 0:
            raise ValueError("ticks_held cannot be negative")
        for name in ("inventory", "imbalance", "spread_bps"):
            if not isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")


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
    else:
        stop_price = position.entry_price + stop_multiple * volatility
        target_price = position.entry_price - target_multiple * volatility
        if float(current.high) >= stop_price:
            return _flat("atr_stop")
        if float(current.low) <= target_price:
            return _flat("atr_target")
    return _hold(position, "hold_atr_bracket")


def evaluate_bar_execution_policy(
    genome: StrategyGenome,
    bars: Sequence[MarketBar],
    position: PositionState,
) -> ExecutionDecision:
    if not bars:
        raise ValueError("bar execution policy requires market bars")
    if position.direction is SignalDirection.FLAT:
        signal = evaluate_bar_signal(genome, bars)
        return ExecutionDecision(signal.direction, signal.reason)

    kind = _exit_kind(genome)
    if kind == "cross_reverse":
        signal = evaluate_bar_signal(genome, bars)
        if signal.direction is SignalDirection.FLAT:
            return _hold(position, "hold_cross_reverse")
        if signal.direction is not position.direction:
            return _flat("cross_reverse")
        return _hold(position, "hold_cross_reverse")

    if kind == "atr_bracket":
        return _atr_bracket(genome, bars, position)

    if kind == "mean_cross":
        window = int(genome.exit["window"])
        if window <= 0 or len(bars) < window:
            return _hold(position, "mean_exit_warmup")
        current = float(bars[-1].close)
        average = fmean(float(item.close) for item in bars[-window:])
        if position.direction is SignalDirection.LONG and current >= average:
            return _flat("mean_cross")
        if position.direction is SignalDirection.SHORT and current <= average:
            return _flat("mean_cross")
        return _hold(position, "hold_mean_cross")

    if kind == "trailing_stop":
        trail_pct = float(genome.exit["trail_pct"])
        if trail_pct <= 0.0 or trail_pct >= 1.0:
            raise ValueError("trail_pct must be between zero and one")
        current = bars[-1]
        if position.direction is SignalDirection.LONG:
            stop_price = position.peak_price * (1.0 - trail_pct)
            if float(current.low) <= stop_price:
                return _flat("trailing_stop")
        else:
            stop_price = position.trough_price * (1.0 + trail_pct)
            if float(current.high) >= stop_price:
                return _flat("trailing_stop")
        return _hold(position, "hold_trailing_stop")

    if kind == "time_or_trend":
        max_bars = int(genome.exit["max_bars"])
        if max_bars <= 0:
            raise ValueError("max_bars must be positive")
        if position.bars_held >= max_bars:
            return _flat("time_exit")
        signal = evaluate_bar_signal(genome, bars)
        if signal.direction is not SignalDirection.FLAT and signal.direction is not position.direction:
            return _flat("trend_reversal")
        return _hold(position, "hold_time_or_trend")

    if kind == "time_or_atr":
        max_bars = int(genome.exit["max_bars"])
        if max_bars <= 0:
            raise ValueError("max_bars must be positive")
        if position.bars_held >= max_bars:
            return _flat("time_exit")
        atr_decision = _atr_bracket(genome, bars, position)
        if atr_decision.close_position:
            return atr_decision
        return _hold(position, "hold_time_or_atr")

    if kind == "time_or_volatility":
        max_bars = int(genome.exit["max_bars"])
        max_volatility = float(genome.exit["max_realized_volatility"])
        if max_bars <= 0 or max_volatility <= 0.0:
            raise ValueError("time_or_volatility requires positive bounds")
        if position.bars_held >= max_bars:
            return _flat("time_exit")
        current = bars[-1]
        observed = current.extras.get("realized_volatility", current.extras.get("rv"))
        if observed is not None and float(observed) >= max_volatility:
            return _flat("volatility_exit")
        return _hold(position, "hold_time_or_volatility")

    if kind == "greeks_or_time":
        max_bars = int(genome.exit["max_bars"])
        max_abs_delta = float(genome.exit["max_abs_delta"])
        max_abs_gamma = float(genome.exit["max_abs_gamma"])
        max_abs_vega = float(genome.exit["max_abs_vega"])
        if max_bars <= 0:
            raise ValueError("greeks_or_time max_bars must be positive")
        if any(value <= 0.0 for value in (max_abs_delta, max_abs_gamma, max_abs_vega)):
            raise ValueError("greeks_or_time Greek bounds must be positive")
        if position.bars_held >= max_bars:
            return _flat("time_exit")
        extras = bars[-1].extras
        greek_values = {
            "delta": abs(float(extras.get("delta", 0.0))),
            "gamma": abs(float(extras.get("gamma", 0.0))),
            "vega": abs(float(extras.get("vega", 0.0))),
        }
        if greek_values["delta"] >= max_abs_delta:
            return _flat("delta_exit")
        if greek_values["gamma"] >= max_abs_gamma:
            return _flat("gamma_exit")
        if greek_values["vega"] >= max_abs_vega:
            return _flat("vega_exit")
        return _hold(position, "hold_greeks_or_time")

    raise ValueError(f"unsupported bar exit policy: {kind}")


def evaluate_hft_execution_policy(
    genome: StrategyGenome,
    state: HftPositionState,
) -> ExecutionDecision:
    kind = _exit_kind(genome)
    if kind == "ticks_or_timeout":
        take_profit_ticks = int(genome.exit["take_profit_ticks"])
        stop_loss_ticks = int(genome.exit["stop_loss_ticks"])
        max_ticks = int(genome.exit["max_ticks"])
        if min(take_profit_ticks, stop_loss_ticks, max_ticks) <= 0:
            raise ValueError("ticks_or_timeout bounds must be positive")
        signed_ticks = (state.current_price - state.entry_price) / state.tick_size
        if state.direction is SignalDirection.SHORT:
            signed_ticks = -signed_ticks
        if signed_ticks >= take_profit_ticks:
            return _flat("hft_take_profit")
        if signed_ticks <= -stop_loss_ticks:
            return _flat("hft_stop_loss")
        if state.ticks_held >= max_ticks:
            return _flat("hft_timeout")
        return ExecutionDecision(state.direction, "hold_hft_ticks", False)

    if kind == "inventory_or_timeout":
        max_inventory = float(genome.exit["max_inventory"])
        max_ticks = int(genome.exit["max_ticks"])
        if not isfinite(max_inventory) or max_inventory <= 0.0 or max_ticks <= 0:
            raise ValueError("inventory_or_timeout bounds must be positive")
        if abs(state.inventory) >= max_inventory:
            return _flat("hft_inventory_limit")
        if state.ticks_held >= max_ticks:
            return _flat("hft_timeout")
        return ExecutionDecision(state.direction, "hold_hft_inventory", False)

    if kind == "imbalance_flip":
        threshold = float(genome.exit["threshold"])
        max_ticks = int(genome.exit["max_ticks"])
        if not isfinite(threshold) or threshold <= 0.0 or max_ticks <= 0:
            raise ValueError("imbalance_flip bounds must be positive")
        if state.direction is SignalDirection.LONG and state.imbalance <= -threshold:
            return _flat("hft_imbalance_flip")
        if state.direction is SignalDirection.SHORT and state.imbalance >= threshold:
            return _flat("hft_imbalance_flip")
        if state.ticks_held >= max_ticks:
            return _flat("hft_timeout")
        return ExecutionDecision(state.direction, "hold_hft_imbalance", False)

    if kind == "spread_convergence":
        exit_bps = float(genome.exit["exit_bps"])
        if not isfinite(exit_bps) or exit_bps < 0.0:
            raise ValueError("exit_bps must be finite and non-negative")
        if abs(state.spread_bps) <= exit_bps:
            return _flat("hft_spread_convergence")
        return ExecutionDecision(state.direction, "hold_hft_spread", False)

    raise ValueError(f"unsupported HFT exit policy: {kind}")


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


def _target_legs(genome: StrategyGenome, legs: Mapping[str, float]) -> dict[str, float]:
    normalized = _float_legs(legs)
    if not normalized:
        return _zero_legs(genome)
    if set(normalized) != set(genome.instruments):
        raise ValueError("signal legs must match the strategy instrument set exactly")
    if any(not isfinite(weight) for weight in normalized.values()):
        raise ValueError("signal leg weights must be finite")
    return normalized


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
    legs = _target_legs(genome, current_legs)
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
    open_legs = _target_legs(genome, current_legs)

    aligned = _aligned_multileg_bars(genome, bars_by_instrument)
    is_open = any(abs(weight) > 0.0 for weight in open_legs.values())

    if not is_open:
        signal = evaluate_multileg_signal(genome, aligned)
        legs = _target_legs(genome, signal.legs)
        return ExecutionDecision(
            _direction_from_legs(genome, legs),
            signal.reason,
            False,
            legs,
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
        legs = _target_legs(genome, signal.legs)
        return ExecutionDecision(
            _direction_from_legs(genome, legs),
            "rebalance",
            False,
            legs,
            True,
        )

    raise ValueError(f"unsupported multi-leg exit policy: {kind}")
