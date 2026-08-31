from __future__ import annotations

from datetime import datetime, timezone

from mastertrd.contracts import MarketBar
from mastertrd.execution_policy import PositionState, evaluate_execution_policy
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome


def _genome(exit_rule: dict) -> StrategyGenome:
    return StrategyGenome(
        strategy_id="options-exit-policy",
        family="options",
        style="options",
        instruments=("ETH-OPTION.TEST",),
        timeframe="1h",
        entry={"type": "volatility_signal", "iv_rv_ratio": 1.1},
        exit=exit_rule,
        filters={"defined_risk_only": True},
        allow_short=False,
    )


def _bar(*, days_to_expiry: float) -> MarketBar:
    return MarketBar(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        venue="TEST",
        instrument="ETH-OPTION.TEST",
        timeframe="1h",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        volume=10.0,
        extras={"days_to_expiry": days_to_expiry},
    )


def test_greeks_or_time_exit_closes_open_option_inside_configured_expiry_window() -> None:
    genome = _genome({"type": "greeks_or_time_exit", "max_days": 7})
    position = PositionState(
        direction=SignalDirection.LONG,
        entry_price=100.0,
        peak_price=101.0,
        trough_price=99.0,
        bars_held=3,
    )

    decision = evaluate_execution_policy(genome, (_bar(days_to_expiry=5.0),), position)

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "option_time_exit"
