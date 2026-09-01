from __future__ import annotations

from datetime import datetime, timezone

import pytest

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


def _bar(*, days_to_expiry: float, **option_state: float) -> MarketBar:
    extras = {"days_to_expiry": days_to_expiry, **option_state}
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
        extras=extras,
    )


def _long() -> PositionState:
    return PositionState(
        direction=SignalDirection.LONG,
        entry_price=100.0,
        peak_price=101.0,
        trough_price=99.0,
        bars_held=3,
    )


def test_greeks_or_time_exit_closes_open_option_inside_configured_expiry_window() -> None:
    genome = _genome({"type": "greeks_or_time_exit", "max_days": 7})

    decision = evaluate_execution_policy(genome, (_bar(days_to_expiry=5.0),), _long())

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "option_time_exit"


@pytest.mark.parametrize(
    ("limit_name", "state_name", "observed"),
    (
        ("max_abs_delta", "delta", -0.8),
        ("max_abs_gamma", "gamma", 0.3),
        ("max_abs_vega", "vega", -0.6),
        ("max_abs_theta", "theta", -0.4),
    ),
)
def test_greeks_or_time_exit_closes_when_configured_greek_limit_is_breached(
    limit_name: str,
    state_name: str,
    observed: float,
) -> None:
    genome = _genome({"type": "greeks_or_time_exit", "max_days": 1, limit_name: 0.2})

    decision = evaluate_execution_policy(
        genome,
        (_bar(days_to_expiry=30.0, **{state_name: observed}),),
        _long(),
    )

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == f"option_{state_name}_exit"


def test_greeks_or_time_exit_fails_closed_when_configured_greek_state_is_missing() -> None:
    genome = _genome({"type": "greeks_or_time_exit", "max_days": 1, "max_abs_delta": 0.5})

    with pytest.raises(ValueError, match="delta"):
        evaluate_execution_policy(genome, (_bar(days_to_expiry=30.0),), _long())
