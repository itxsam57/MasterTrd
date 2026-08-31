from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mastertrd.contracts import MarketBar
from mastertrd.execution_policy import evaluate_multileg_execution_policy
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome


LEFT = "ETHUSDT.BINANCE"
RIGHT = "BTCUSDT.BINANCE"


def _bars(instrument: str, closes: list[float], *, extras: list[dict] | None = None) -> tuple[MarketBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output = []
    metadata = extras or [{} for _ in closes]
    for index, (close, extra) in enumerate(zip(closes, metadata, strict=True)):
        output.append(
            MarketBar(
                timestamp=start + timedelta(hours=index),
                venue="BINANCE",
                instrument=instrument,
                timeframe="1h",
                open=close,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=100.0,
                extras=extra,
            )
        )
    return tuple(output)


def _genome(family: str, entry: dict, exit_rule: dict) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=f"policy-{family}",
        family=family,
        style=family,
        instruments=(LEFT, RIGHT),
        timeframe="1h",
        entry=entry,
        exit=exit_rule,
        allow_short=True,
    )


def test_spread_mean_exit_flattens_both_open_legs_inside_exit_band() -> None:
    genome = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.5},
        {"type": "spread_mean_exit", "z_exit": 0.5},
    )
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [109.0, 110.0, 111.0, 110.0]),
            RIGHT: _bars(RIGHT, [100.0, 100.0, 100.0, 100.0]),
        },
        current_legs={LEFT: -1.0, RIGHT: 1.0},
        bars_held=4,
    )

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "spread_mean_exit"
    assert decision.legs == {LEFT: 0.0, RIGHT: 0.0}


def test_spread_mean_exit_holds_open_legs_while_spread_is_still_extreme() -> None:
    genome = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.5},
        {"type": "spread_mean_exit", "z_exit": 0.5},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [109.0, 110.0, 111.0, 125.0]),
            RIGHT: _bars(RIGHT, [100.0, 100.0, 100.0, 100.0]),
        },
        current_legs=current,
        bars_held=4,
    )

    assert decision.close_position is False
    assert decision.reason == "hold_spread_mean_exit"
    assert decision.legs == current


def test_funding_edge_decay_flattens_when_edge_falls_below_exit_threshold() -> None:
    genome = _genome(
        "funding_basis",
        {"type": "funding_basis", "min_edge_bps": 20},
        {"type": "edge_decay", "exit_bps": 5},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [100.0, 100.0], extras=[{}, {"basis_bps": 3.0}]),
            RIGHT: _bars(RIGHT, [100.0, 100.0]),
        },
        current_legs=current,
        bars_held=2,
    )

    assert decision.close_position is True
    assert decision.reason == "edge_decay"
    assert decision.legs == {LEFT: 0.0, RIGHT: 0.0}


def test_delta_neutral_rebalance_marks_adjustment_without_flattening() -> None:
    genome = _genome(
        "delta_neutral",
        {"type": "hedged_basis", "hedge_ratio": 1.0},
        {"type": "rebalance", "drift_bps": 25},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [100.0, 110.0], extras=[{}, {"hedge_drift_bps": 40.0}]),
            RIGHT: _bars(RIGHT, [100.0, 100.0]),
        },
        current_legs=current,
        bars_held=2,
    )

    assert decision.close_position is False
    assert decision.rebalance_position is True
    assert decision.reason == "rebalance"
    assert set(decision.legs) == {LEFT, RIGHT}


def test_multileg_exit_policy_fails_closed_when_required_rebalance_state_is_missing() -> None:
    genome = _genome(
        "delta_neutral",
        {"type": "hedged_basis", "hedge_ratio": 1.0},
        {"type": "rebalance", "drift_bps": 25},
    )
    with pytest.raises(ValueError, match="hedge_drift_bps"):
        evaluate_multileg_execution_policy(
            genome,
            {LEFT: _bars(LEFT, [100.0, 110.0]), RIGHT: _bars(RIGHT, [100.0, 100.0])},
            current_legs={LEFT: -1.0, RIGHT: 1.0},
            bars_held=2,
        )
