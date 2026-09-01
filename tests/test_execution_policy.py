from datetime import datetime, timedelta, timezone

import pytest

from mastertrd.contracts import MarketBar
from mastertrd.execution_policy import PositionState, evaluate_execution_policy
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome


def _bars(closes: list[float]) -> tuple[MarketBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    previous = closes[0]
    for index, close in enumerate(closes):
        bars.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                venue="BINANCE",
                instrument="ETHUSDT.BINANCE",
                timeframe="1m",
                open=previous,
                high=max(previous, close) + 1.0,
                low=min(previous, close) - 1.0,
                close=close,
                volume=100.0,
            )
        )
        previous = close
    return tuple(bars)


def _genome(entry: dict, exit_rule: dict, *, allow_short: bool = True) -> StrategyGenome:
    return StrategyGenome(
        strategy_id="exit-policy-1",
        family="momentum",
        style="intraday",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry=entry,
        exit=exit_rule,
        allow_short=allow_short,
    )


def _long(entry: float, peak: float, trough: float, bars_held: int = 1) -> PositionState:
    return PositionState(SignalDirection.LONG, entry, peak, trough, bars_held)


def _short(entry: float, peak: float, trough: float, bars_held: int = 1) -> PositionState:
    return PositionState(SignalDirection.SHORT, entry, peak, trough, bars_held)


def test_position_state_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        PositionState(SignalDirection.FLAT, -1.0, 0.0, 0.0, 0)
    with pytest.raises(ValueError, match="positive entry_price"):
        PositionState(SignalDirection.LONG, 0.0, 1.0, 0.0, 0)
    with pytest.raises(ValueError, match="bars_held"):
        PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, -1)
    with pytest.raises(ValueError, match="peak_price"):
        PositionState(SignalDirection.LONG, 100.0, 99.0, 101.0, 1)
    with pytest.raises(ValueError, match="observed position range"):
        PositionState(SignalDirection.LONG, 100.0, 99.0, 98.0, 1)


def test_flat_position_uses_entry_signal() -> None:
    genome = StrategyGenome(
        strategy_id="entry-policy-1",
        family="trend",
        style="trend",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "ema_cross", "fast": 2, "slow": 4},
        exit={"type": "cross_reverse"},
        allow_short=True,
    )
    decision = evaluate_execution_policy(
        genome,
        _bars([100.0, 102.0, 104.0, 106.0, 108.0]),
        PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0),
    )
    assert decision.direction is SignalDirection.LONG
    assert decision.close_position is False
    assert decision.reason == "ema_cross"


def test_execution_policy_requires_market_data() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 2.0},
    )
    with pytest.raises(ValueError, match="market bars"):
        evaluate_execution_policy(genome, (), _long(100.0, 100.0, 100.0))


def test_atr_bracket_closes_long_when_stop_is_hit() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 2.0, "atr_period": 3},
    )
    decision = evaluate_execution_policy(
        genome,
        _bars([100.0, 101.0, 102.0, 103.0, 99.0]),
        _long(103.0, 103.0, 99.0),
    )
    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "atr_stop"


def test_atr_bracket_closes_long_when_target_is_hit() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 1.0, "atr_period": 3},
    )
    decision = evaluate_execution_policy(
        genome,
        _bars([100.0, 101.0, 102.0, 103.0, 108.0]),
        _long(103.0, 108.0, 103.0),
    )
    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "atr_target"


def test_atr_bracket_handles_short_stop_target_hold_and_warmup() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 1.0, "atr_period": 3},
    )
    stopped = evaluate_execution_policy(
        genome,
        _bars([100.0, 99.0, 98.0, 97.0, 104.0]),
        _short(97.0, 104.0, 97.0),
    )
    targeted = evaluate_execution_policy(
        genome,
        _bars([100.0, 99.0, 98.0, 97.0, 90.0]),
        _short(97.0, 97.0, 90.0),
    )
    held = evaluate_execution_policy(
        genome,
        _bars([100.0, 99.0, 98.0, 97.0, 97.5]),
        _short(97.0, 98.0, 97.0),
    )
    warm = evaluate_execution_policy(
        genome,
        _bars([100.0, 99.0, 98.0, 97.0]),
        _short(98.0, 100.0, 97.0),
    )
    assert stopped.reason == "atr_stop" and stopped.close_position
    assert targeted.reason == "atr_target" and targeted.close_position
    assert held.reason == "hold_atr_bracket" and not held.close_position
    assert warm.reason == "atr_exit_warmup" and not warm.close_position


def test_atr_bracket_rejects_invalid_parameters() -> None:
    invalid_period = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 1.0, "atr_period": 0},
    )
    invalid_multiple = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 0.0, "target_atr": 1.0},
    )
    with pytest.raises(ValueError, match="atr_period"):
        evaluate_execution_policy(invalid_period, _bars([100, 101, 102, 103]), _long(102, 103, 102))
    with pytest.raises(ValueError, match="multiples"):
        evaluate_execution_policy(invalid_multiple, _bars([100, 101, 102, 103]), _long(102, 103, 102))


def test_trailing_atr_uses_peak_since_entry_not_entry_price() -> None:
    genome = StrategyGenome(
        strategy_id="trailing-policy-1",
        family="position",
        style="position",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "long_horizon_trend", "fast": 2, "slow": 4},
        exit={"type": "trailing_atr", "atr": 1.0, "atr_period": 3},
        allow_short=True,
    )
    decision = evaluate_execution_policy(
        genome,
        _bars([100.0, 102.0, 105.0, 110.0, 102.0]),
        _long(100.0, 110.0, 100.0, bars_held=4),
    )
    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "trailing_atr"


def test_trailing_atr_handles_short_hold_warmup_and_invalid_multiple() -> None:
    genome = StrategyGenome(
        strategy_id="trailing-policy-2",
        family="position",
        style="position",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "long_horizon_trend", "fast": 2, "slow": 4},
        exit={"type": "trailing_atr", "atr": 1.0, "atr_period": 3},
        allow_short=True,
    )
    triggered = evaluate_execution_policy(
        genome,
        _bars([110.0, 108.0, 105.0, 100.0, 109.0]),
        _short(110.0, 110.0, 100.0, bars_held=4),
    )
    held = evaluate_execution_policy(
        genome,
        _bars([100.0, 102.0, 105.0, 110.0, 109.0]),
        _long(100.0, 110.0, 100.0, bars_held=4),
    )
    warm = evaluate_execution_policy(
        genome,
        _bars([100.0, 101.0, 102.0, 103.0]),
        _long(100.0, 103.0, 100.0),
    )
    invalid = StrategyGenome(
        strategy_id="trailing-policy-3",
        family="position",
        style="position",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "long_horizon_trend", "fast": 2, "slow": 4},
        exit={"type": "trailing_atr", "atr": 0.0},
        allow_short=True,
    )
    assert triggered.reason == "trailing_atr" and triggered.close_position
    assert held.reason == "hold_trailing_atr" and not held.close_position
    assert warm.reason == "trailing_atr_warmup" and not warm.close_position
    with pytest.raises(ValueError, match="multiple"):
        evaluate_execution_policy(invalid, _bars([100, 101, 102, 103]), _long(100, 103, 100))


def test_mean_or_atr_stop_closes_on_mean_for_long_and_short() -> None:
    genome = _genome(
        {"type": "zscore_reversion", "window": 3, "z": 1.0},
        {"type": "mean_or_atr_stop", "stop_atr": 1.0, "atr_period": 3},
    )
    long_exit = evaluate_execution_policy(
        genome,
        _bars([100.0, 100.0, 100.0, 90.0, 100.0]),
        _long(90.0, 100.0, 90.0),
    )
    short_exit = evaluate_execution_policy(
        genome,
        _bars([100.0, 100.0, 100.0, 110.0, 100.0]),
        _short(110.0, 110.0, 100.0),
    )
    assert long_exit.reason == "mean_reversion_exit" and long_exit.close_position
    assert short_exit.reason == "mean_reversion_exit" and short_exit.close_position


def test_mean_or_atr_stop_handles_stops_hold_warmup_and_invalid_config() -> None:
    genome = _genome(
        {"type": "zscore_reversion", "window": 3, "z": 1.0},
        {"type": "mean_or_atr_stop", "stop_atr": 1.0, "atr_period": 3},
    )
    long_stop = evaluate_execution_policy(
        genome,
        _bars([100.0, 99.0, 98.0, 90.0, 80.0]),
        _long(90.0, 90.0, 80.0),
    )
    short_stop = evaluate_execution_policy(
        genome,
        _bars([100.0, 101.0, 102.0, 110.0, 120.0]),
        _short(110.0, 120.0, 110.0),
    )
    held = evaluate_execution_policy(
        genome,
        _bars([100.0, 100.0, 100.0, 90.0, 91.0]),
        _long(90.0, 91.0, 90.0),
    )
    warm = evaluate_execution_policy(
        genome,
        _bars([100.0, 99.0, 98.0]),
        _long(98.0, 100.0, 98.0),
    )
    invalid = _genome(
        {"type": "zscore_reversion", "window": 1, "z": 1.0},
        {"type": "mean_or_atr_stop", "stop_atr": 0.0},
    )
    assert long_stop.reason == "atr_stop" and long_stop.close_position
    assert short_stop.reason == "atr_stop" and short_stop.close_position
    assert held.reason == "hold_mean_or_atr_stop" and not held.close_position
    assert warm.reason == "mean_exit_warmup" and not warm.close_position
    with pytest.raises(ValueError, match="valid window"):
        evaluate_execution_policy(invalid, _bars([100, 99, 98]), _long(98, 100, 98))


def test_cross_reverse_keeps_position_until_entry_signal_reverses() -> None:
    genome = StrategyGenome(
        strategy_id="cross-policy-1",
        family="trend",
        style="trend",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "ema_cross", "fast": 2, "slow": 4},
        exit={"type": "cross_reverse"},
        allow_short=True,
    )
    held = evaluate_execution_policy(
        genome,
        _bars([100.0, 102.0, 104.0, 106.0, 108.0]),
        _long(104.0, 108.0, 104.0, bars_held=2),
    )
    warm = evaluate_execution_policy(
        genome,
        _bars([100.0, 101.0]),
        _long(100.0, 101.0, 100.0),
    )
    assert held.direction is SignalDirection.LONG
    assert held.close_position is False
    assert held.reason == "hold_cross_reverse"
    assert warm.direction is SignalDirection.LONG
    assert warm.close_position is False


def test_cross_reverse_reverses_or_flattens_when_shorting_is_disabled() -> None:
    bars = _bars([108.0, 106.0, 104.0, 102.0, 100.0])
    shortable = StrategyGenome(
        strategy_id="cross-policy-2",
        family="trend",
        style="trend",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "ema_cross", "fast": 2, "slow": 4},
        exit={"type": "cross_reverse"},
        allow_short=True,
    )
    long_only = StrategyGenome(
        strategy_id="cross-policy-3",
        family="trend",
        style="trend",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"type": "ema_cross", "fast": 2, "slow": 4},
        exit={"type": "cross_reverse"},
        allow_short=False,
    )
    reversed_decision = evaluate_execution_policy(shortable, bars, _long(104.0, 108.0, 100.0))
    flat_decision = evaluate_execution_policy(long_only, bars, _long(104.0, 108.0, 100.0))
    assert reversed_decision.direction is SignalDirection.SHORT
    assert reversed_decision.close_position is True
    assert reversed_decision.reason == "cross_reverse"
    assert flat_decision.direction is SignalDirection.FLAT
    assert flat_decision.close_position is True


def test_missing_and_unknown_exit_policy_fail_closed() -> None:
    missing = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"unexpected": "value"},
    )
    unknown = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "unimplemented_exit"},
    )
    position = _long(102.0, 103.0, 102.0)
    with pytest.raises(ValueError, match="exit policy is required"):
        evaluate_execution_policy(missing, _bars([100, 101, 102, 103]), position)
    with pytest.raises(ValueError, match="unsupported exit policy"):
        evaluate_execution_policy(unknown, _bars([100, 101, 102, 103]), position)
