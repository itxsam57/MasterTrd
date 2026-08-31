from datetime import datetime, timedelta, timezone

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


def _genome(entry: dict, exit_rule: dict) -> StrategyGenome:
    return StrategyGenome(
        strategy_id="exit-policy-1",
        family="momentum",
        style="intraday",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry=entry,
        exit=exit_rule,
        allow_short=True,
    )


def test_atr_bracket_closes_long_when_stop_is_hit() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 2.0, "atr_period": 3},
    )
    bars = _bars([100.0, 101.0, 102.0, 103.0, 99.0])
    position = PositionState(
        direction=SignalDirection.LONG,
        entry_price=103.0,
        peak_price=103.0,
        trough_price=99.0,
        bars_held=1,
    )

    decision = evaluate_execution_policy(genome, bars, position)

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "atr_stop"


def test_atr_bracket_closes_long_when_target_is_hit() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "atr_bracket", "stop_atr": 1.0, "target_atr": 1.0, "atr_period": 3},
    )
    bars = _bars([100.0, 101.0, 102.0, 103.0, 108.0])
    position = PositionState(
        direction=SignalDirection.LONG,
        entry_price=103.0,
        peak_price=108.0,
        trough_price=103.0,
        bars_held=1,
    )

    decision = evaluate_execution_policy(genome, bars, position)

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "atr_target"


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
    bars = _bars([100.0, 102.0, 105.0, 110.0, 102.0])
    position = PositionState(
        direction=SignalDirection.LONG,
        entry_price=100.0,
        peak_price=110.0,
        trough_price=100.0,
        bars_held=4,
    )

    decision = evaluate_execution_policy(genome, bars, position)

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "trailing_atr"


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
    bars = _bars([100.0, 102.0, 104.0, 106.0, 108.0])
    position = PositionState(
        direction=SignalDirection.LONG,
        entry_price=104.0,
        peak_price=108.0,
        trough_price=104.0,
        bars_held=2,
    )

    decision = evaluate_execution_policy(genome, bars, position)

    assert decision.direction is SignalDirection.LONG
    assert decision.close_position is False
    assert decision.reason == "hold_cross_reverse"


def test_unknown_exit_policy_fails_closed() -> None:
    genome = _genome(
        {"type": "rsi_momentum", "period": 3, "threshold": 55},
        {"type": "unimplemented_exit"},
    )

    try:
        evaluate_execution_policy(
            genome,
            _bars([100.0, 101.0, 102.0, 103.0]),
            PositionState(
                direction=SignalDirection.LONG,
                entry_price=102.0,
                peak_price=103.0,
                trough_price=102.0,
                bars_held=1,
            ),
        )
    except ValueError as exc:
        assert "unsupported exit policy" in str(exc)
    else:
        raise AssertionError("unsupported exit policy must fail closed")
