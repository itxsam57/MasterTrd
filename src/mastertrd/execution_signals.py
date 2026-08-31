from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import sqrt
from statistics import fmean
from typing import Mapping, Sequence

from .contracts import MarketBar
from .genome import StrategyGenome


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class SignalDecision:
    direction: SignalDirection
    reason: str
    score: float = 0.0
    legs: Mapping[str, int] = field(default_factory=dict)


def _entry_kind(genome: StrategyGenome) -> str:
    value = genome.entry.get("kind", genome.entry.get("type"))
    if not value:
        raise ValueError("strategy entry kind is required")
    return str(value)


def _closes(bars: Sequence[MarketBar]) -> list[float]:
    return [float(bar.close) for bar in bars]


def ema(values: Sequence[float], period: int) -> float:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    if len(values) < period:
        raise ValueError("insufficient values for EMA")
    seed = fmean(float(value) for value in values[:period])
    alpha = 2.0 / (period + 1.0)
    current = seed
    for value in values[period:]:
        current = alpha * float(value) + (1.0 - alpha) * current
    return current


def rsi(values: Sequence[float], period: int) -> float:
    if period <= 0:
        raise ValueError("RSI period must be positive")
    if len(values) <= period:
        raise ValueError("insufficient values for RSI")
    deltas = [float(values[index]) - float(values[index - 1]) for index in range(1, len(values))]
    gains = [max(delta, 0.0) for delta in deltas]
    losses = [max(-delta, 0.0) for delta in deltas]
    avg_gain = fmean(gains[:period])
    avg_loss = fmean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        avg_gain = ((period - 1) * avg_gain + gain) / period
        avg_loss = ((period - 1) * avg_loss + loss) / period
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    relative = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative))


def atr(bars: Sequence[MarketBar], period: int) -> float:
    if period <= 0:
        raise ValueError("ATR period must be positive")
    if len(bars) <= period:
        raise ValueError("insufficient bars for ATR")
    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        bar = bars[index]
        previous_close = float(bars[index - 1].close)
        true_ranges.append(
            max(
                float(bar.high) - float(bar.low),
                abs(float(bar.high) - previous_close),
                abs(float(bar.low) - previous_close),
            )
        )
    current = fmean(true_ranges[:period])
    for value in true_ranges[period:]:
        current = ((period - 1) * current + value) / period
    return current


def _zscore(value: float, history: Sequence[float]) -> float:
    if len(history) < 2:
        raise ValueError("z-score history requires at least two values")
    mean = fmean(float(item) for item in history)
    variance = fmean((float(item) - mean) ** 2 for item in history)
    deviation = sqrt(variance)
    if deviation == 0.0:
        if value == mean:
            return 0.0
        return float("inf") if value > mean else float("-inf")
    return (float(value) - mean) / deviation


def _flat(reason: str) -> SignalDecision:
    return SignalDecision(SignalDirection.FLAT, reason, 0.0)


def evaluate_bar_signal(genome: StrategyGenome, bars: Sequence[MarketBar]) -> SignalDecision:
    if not bars:
        return _flat("no_bars")
    kind = _entry_kind(genome)
    closes = _closes(bars)

    if kind == "ema_cross":
        fast = int(genome.entry.get("fast_period", genome.entry.get("fast", 0)))
        slow = int(genome.entry.get("slow_period", genome.entry.get("slow", 0)))
        if fast <= 0 or slow <= 0 or fast >= slow or len(closes) < slow:
            return _flat("ema_warmup")
        fast_value = ema(closes, fast)
        slow_value = ema(closes, slow)
        direction = SignalDirection.LONG if fast_value > slow_value else SignalDirection.SHORT
        return SignalDecision(direction, "ema_cross", fast_value - slow_value)

    if kind == "rsi_momentum":
        period = int(genome.entry["period"])
        threshold = float(genome.entry["threshold"])
        if len(closes) <= period:
            return _flat("rsi_warmup")
        value = rsi(closes, period)
        if value >= threshold:
            return SignalDecision(SignalDirection.LONG, "rsi_momentum", value)
        if value <= 100.0 - threshold:
            return SignalDecision(SignalDirection.SHORT, "rsi_momentum", -value)
        return _flat("rsi_neutral")

    if kind == "donchian_breakout":
        window = int(genome.entry["window"])
        if window <= 0 or len(bars) <= window:
            return _flat("donchian_warmup")
        prior = bars[-window - 1 : -1]
        upper = max(float(bar.high) for bar in prior)
        lower = min(float(bar.low) for bar in prior)
        current = float(bars[-1].close)
        if current > upper:
            return SignalDecision(SignalDirection.LONG, "donchian_breakout", current - upper)
        if current < lower:
            return SignalDecision(SignalDirection.SHORT, "donchian_breakout", lower - current)
        return _flat("donchian_inside")

    if kind == "zscore_reversion":
        window = int(genome.entry["window"])
        threshold = float(genome.entry["z"])
        if window < 2 or len(closes) <= window:
            return _flat("zscore_warmup")
        value = _zscore(closes[-1], closes[-window - 1 : -1])
        if value <= -threshold:
            return SignalDecision(SignalDirection.LONG, "zscore_reversion", -value)
        if value >= threshold:
            return SignalDecision(SignalDirection.SHORT, "zscore_reversion", value)
        return _flat("zscore_neutral")

    if kind == "volatility_breakout":
        lookback = int(genome.entry["lookback"])
        multiplier = float(genome.entry["multiplier"])
        if lookback <= 0 or len(bars) <= lookback:
            return _flat("volatility_warmup")
        range_value = atr(bars, lookback)
        anchor = float(bars[-2].close)
        current = float(bars[-1].close)
        if current > anchor + multiplier * range_value:
            return SignalDecision(SignalDirection.LONG, "volatility_breakout", current - anchor)
        if current < anchor - multiplier * range_value:
            return SignalDecision(SignalDirection.SHORT, "volatility_breakout", anchor - current)
        return _flat("volatility_inside")

    if kind == "pullback_trend":
        fast = int(genome.entry["fast"])
        slow = int(genome.entry["slow"])
        rsi_period = int(genome.entry["rsi"])
        minimum = max(slow, rsi_period + 1)
        if len(closes) < minimum:
            return _flat("pullback_warmup")
        fast_value = ema(closes, fast)
        slow_value = ema(closes, slow)
        momentum = rsi(closes, rsi_period)
        if fast_value > slow_value and momentum >= 45.0:
            return SignalDecision(SignalDirection.LONG, "pullback_trend", fast_value - slow_value)
        if fast_value < slow_value and momentum <= 55.0:
            return SignalDecision(SignalDirection.SHORT, "pullback_trend", slow_value - fast_value)
        return _flat("pullback_neutral")

    if kind == "long_horizon_trend":
        fast = int(genome.entry["fast"])
        slow = int(genome.entry["slow"])
        if len(closes) < slow:
            return _flat("position_warmup")
        fast_value = ema(closes, fast)
        slow_value = ema(closes, slow)
        direction = SignalDirection.LONG if fast_value > slow_value else SignalDirection.SHORT
        return SignalDecision(direction, "long_horizon_trend", abs(fast_value - slow_value))

    if kind == "volatility_signal":
        ratio_limit = float(genome.entry["iv_rv_ratio"])
        extras = bars[-1].extras
        iv = extras.get("implied_volatility", extras.get("iv"))
        rv = extras.get("realized_volatility", extras.get("rv"))
        if iv is None or rv is None or float(rv) <= 0.0:
            return _flat("options_volatility_data_missing")
        ratio = float(iv) / float(rv)
        if ratio < ratio_limit:
            return SignalDecision(SignalDirection.LONG, "volatility_signal", ratio_limit - ratio)
        if ratio > ratio_limit:
            return SignalDecision(SignalDirection.SHORT, "volatility_signal", ratio - ratio_limit)
        return _flat("volatility_fair")

    if kind in {"cointegration_spread", "funding_basis", "hedged_basis", "strategy_rotation"}:
        raise ValueError(f"{kind} requires multi-leg signal evaluation")

    raise ValueError(f"unsupported bar entry kind: {kind}")


def evaluate_multileg_signal(
    genome: StrategyGenome,
    bars_by_instrument: Mapping[str, Sequence[MarketBar]],
) -> SignalDecision:
    kind = _entry_kind(genome)
    missing = [instrument for instrument in genome.instruments if instrument not in bars_by_instrument]
    if missing:
        raise ValueError(f"missing multi-leg bars for: {', '.join(missing)}")
    if len(genome.instruments) < 2:
        raise ValueError("multi-leg strategy requires at least two instruments")

    left_id, right_id = genome.instruments[:2]
    left = bars_by_instrument[left_id]
    right = bars_by_instrument[right_id]
    count = min(len(left), len(right))
    if count == 0:
        return _flat("no_multileg_bars")

    if kind == "cointegration_spread":
        window = int(genome.entry["window"])
        threshold = float(genome.entry["z_entry"])
        if count <= window:
            return _flat("spread_warmup")
        spreads = [float(left[-count + index].close) - float(right[-count + index].close) for index in range(count)]
        value = _zscore(spreads[-1], spreads[-window - 1 : -1])
        if value >= threshold:
            return SignalDecision(
                SignalDirection.SHORT,
                "cointegration_spread",
                value,
                legs={left_id: -1, right_id: 1},
            )
        if value <= -threshold:
            return SignalDecision(
                SignalDirection.LONG,
                "cointegration_spread",
                -value,
                legs={left_id: 1, right_id: -1},
            )
        return _flat("spread_neutral")

    if kind == "funding_basis":
        minimum = float(genome.entry["min_edge_bps"])
        edge = left[-1].extras.get("basis_bps")
        if edge is None:
            left_funding = float(left[-1].extras.get("funding_rate", 0.0))
            right_funding = float(right[-1].extras.get("funding_rate", 0.0))
            edge = (left_funding - right_funding) * 10_000.0
        edge_value = float(edge)
        if abs(edge_value) < minimum:
            return _flat("funding_edge_too_small")
        sign = -1 if edge_value > 0 else 1
        direction = SignalDirection.SHORT if sign < 0 else SignalDirection.LONG
        return SignalDecision(direction, "funding_basis", abs(edge_value), {left_id: sign, right_id: -sign})

    if kind == "hedged_basis":
        ratio = float(genome.entry["hedge_ratio"])
        if ratio <= 0.0:
            raise ValueError("hedge_ratio must be positive")
        left_close = float(left[-1].close)
        right_close = float(right[-1].close)
        edge = left_close - ratio * right_close
        if edge == 0.0:
            return _flat("hedged_basis_balanced")
        sign = -1 if edge > 0.0 else 1
        direction = SignalDirection.SHORT if sign < 0 else SignalDirection.LONG
        return SignalDecision(direction, "hedged_basis", abs(edge), {left_id: sign, right_id: -sign})

    if kind == "strategy_rotation":
        lookback = int(genome.entry["lookback"])
        scores: dict[str, float] = {}
        for instrument in genome.instruments:
            series = bars_by_instrument[instrument]
            if len(series) <= lookback:
                return _flat("rotation_warmup")
            start = float(series[-lookback - 1].close)
            end = float(series[-1].close)
            if start == 0.0:
                raise ValueError("rotation start price cannot be zero")
            scores[instrument] = end / start - 1.0
        winner = max(scores, key=scores.get)
        if scores[winner] <= 0.0:
            return _flat("rotation_no_positive_asset")
        legs = {instrument: int(instrument == winner) for instrument in genome.instruments}
        return SignalDecision(SignalDirection.LONG, "strategy_rotation", scores[winner], legs)

    raise ValueError(f"unsupported multi-leg entry kind: {kind}")
