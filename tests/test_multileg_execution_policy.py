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


def _genome(family: str, entry: dict, exit_rule: dict, *, instruments: tuple[str, ...] = (LEFT, RIGHT)) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=f"policy-{family}",
        family=family,
        style=family,
        instruments=instruments,
        timeframe="1h",
        entry=entry,
        exit=exit_rule,
        allow_short=True,
    )


def test_flat_multileg_state_uses_shared_entry_signal() -> None:
    genome = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        {"type": "spread_mean_exit", "z_exit": 0.5},
    )
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [100.0, 100.0, 100.0, 120.0]),
            RIGHT: _bars(RIGHT, [100.0, 100.0, 100.0, 100.0]),
        },
        current_legs={LEFT: 0.0, RIGHT: 0.0},
        bars_held=0,
    )
    assert decision.direction is SignalDirection.SHORT
    assert decision.legs == {LEFT: -1.0, RIGHT: 1.0}
    assert decision.close_position is False


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


def test_spread_mean_exit_warms_up_and_rejects_bad_config() -> None:
    warm = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 4, "z_entry": 1.5},
        {"type": "spread_mean_exit", "z_exit": 0.5},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    decision = evaluate_multileg_execution_policy(
        warm,
        {LEFT: _bars(LEFT, [100.0, 101.0]), RIGHT: _bars(RIGHT, [100.0, 100.0])},
        current_legs=current,
        bars_held=2,
    )
    assert decision.reason == "spread_exit_warmup"
    assert decision.legs == current

    invalid = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 1, "z_entry": 1.5},
        {"type": "spread_mean_exit", "z_exit": -0.1},
    )
    with pytest.raises(ValueError, match="spread mean exit"):
        evaluate_multileg_execution_policy(
            invalid,
            {LEFT: _bars(LEFT, [100.0, 101.0]), RIGHT: _bars(RIGHT, [100.0, 100.0])},
            current_legs=current,
            bars_held=2,
        )


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


def test_funding_edge_decay_uses_real_funding_fallback_and_can_hold() -> None:
    genome = _genome(
        "funding_basis",
        {"type": "funding_basis", "min_edge_bps": 20},
        {"type": "edge_decay", "exit_bps": 5},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [100.0], extras=[{"funding_rate": 0.0020}]),
            RIGHT: _bars(RIGHT, [100.0], extras=[{"funding_rate": 0.0001}]),
        },
        current_legs=current,
        bars_held=1,
    )
    assert decision.reason == "hold_edge_decay"
    assert decision.legs == current


def test_funding_edge_decay_fails_closed_on_missing_or_invalid_state() -> None:
    genome = _genome(
        "funding_basis",
        {"type": "funding_basis", "min_edge_bps": 20},
        {"type": "edge_decay", "exit_bps": 5},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    with pytest.raises(ValueError, match="basis_bps or funding_rate"):
        evaluate_multileg_execution_policy(
            genome,
            {LEFT: _bars(LEFT, [100.0]), RIGHT: _bars(RIGHT, [100.0])},
            current_legs=current,
            bars_held=1,
        )

    invalid = _genome(
        "funding_basis",
        {"type": "funding_basis", "min_edge_bps": 20},
        {"type": "edge_decay", "exit_bps": -1},
    )
    with pytest.raises(ValueError, match="cannot be negative"):
        evaluate_multileg_execution_policy(
            invalid,
            {LEFT: _bars(LEFT, [100.0], extras=[{"basis_bps": 2.0}]), RIGHT: _bars(RIGHT, [100.0])},
            current_legs=current,
            bars_held=1,
        )


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


def test_delta_neutral_rebalance_holds_below_drift_threshold() -> None:
    genome = _genome(
        "delta_neutral",
        {"type": "hedged_basis", "hedge_ratio": 1.0},
        {"type": "rebalance", "drift_bps": 25},
    )
    current = {LEFT: -1.0, RIGHT: 1.0}
    decision = evaluate_multileg_execution_policy(
        genome,
        {
            LEFT: _bars(LEFT, [100.0], extras=[{"hedge_drift_bps": 10.0}]),
            RIGHT: _bars(RIGHT, [100.0]),
        },
        current_legs=current,
        bars_held=1,
    )
    assert decision.reason == "hold_rebalance"
    assert decision.rebalance_position is False
    assert decision.legs == current


def test_periodic_portfolio_rebalance_only_runs_on_configured_period() -> None:
    genome = _genome(
        "portfolio",
        {"type": "strategy_rotation", "lookback": 1},
        {"type": "rebalance", "periods": 2},
    )
    current = {LEFT: 1.0, RIGHT: 0.0}
    data = {
        LEFT: _bars(LEFT, [100.0, 101.0, 102.0]),
        RIGHT: _bars(RIGHT, [100.0, 102.0, 105.0]),
    }
    held = evaluate_multileg_execution_policy(genome, data, current_legs=current, bars_held=1)
    rebalanced = evaluate_multileg_execution_policy(genome, data, current_legs=current, bars_held=2)
    assert held.reason == "hold_rebalance"
    assert not held.rebalance_position
    assert rebalanced.reason == "rebalance"
    assert rebalanced.rebalance_position
    assert rebalanced.legs == {LEFT: 0.0, RIGHT: 1.0}


def test_rebalance_config_and_required_state_fail_closed() -> None:
    current = {LEFT: -1.0, RIGHT: 1.0}
    missing_state = _genome(
        "delta_neutral",
        {"type": "hedged_basis", "hedge_ratio": 1.0},
        {"type": "rebalance", "drift_bps": 25},
    )
    with pytest.raises(ValueError, match="hedge_drift_bps"):
        evaluate_multileg_execution_policy(
            missing_state,
            {LEFT: _bars(LEFT, [100.0, 110.0]), RIGHT: _bars(RIGHT, [100.0, 100.0])},
            current_legs=current,
            bars_held=2,
        )

    bad_drift = _genome(
        "delta_neutral",
        {"type": "hedged_basis", "hedge_ratio": 1.0},
        {"type": "rebalance", "drift_bps": 0},
    )
    with pytest.raises(ValueError, match="drift_bps must be positive"):
        evaluate_multileg_execution_policy(
            bad_drift,
            {LEFT: _bars(LEFT, [100.0], extras=[{"hedge_drift_bps": 1.0}]), RIGHT: _bars(RIGHT, [100.0])},
            current_legs=current,
            bars_held=1,
        )

    bad_period = _genome(
        "portfolio",
        {"type": "strategy_rotation", "lookback": 1},
        {"type": "rebalance", "periods": 0},
    )
    with pytest.raises(ValueError, match="periods must be positive"):
        evaluate_multileg_execution_policy(
            bad_period,
            {LEFT: _bars(LEFT, [100.0, 101.0]), RIGHT: _bars(RIGHT, [100.0, 102.0])},
            current_legs={LEFT: 1.0, RIGHT: 0.0},
            bars_held=1,
        )

    missing_config = _genome(
        "portfolio",
        {"type": "strategy_rotation", "lookback": 1},
        {"type": "rebalance"},
    )
    with pytest.raises(ValueError, match="drift_bps or periods"):
        evaluate_multileg_execution_policy(
            missing_config,
            {LEFT: _bars(LEFT, [100.0, 101.0]), RIGHT: _bars(RIGHT, [100.0, 102.0])},
            current_legs={LEFT: 1.0, RIGHT: 0.0},
            bars_held=1,
        )


def test_multileg_policy_rejects_invalid_shape_state_and_unknown_exit() -> None:
    single = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        {"type": "spread_mean_exit", "z_exit": 0.5},
        instruments=(LEFT,),
    )
    with pytest.raises(ValueError, match="at least two instruments"):
        evaluate_multileg_execution_policy(single, {LEFT: _bars(LEFT, [100.0])}, current_legs={LEFT: 0.0}, bars_held=0)

    genome = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        {"type": "spread_mean_exit", "z_exit": 0.5},
    )
    with pytest.raises(ValueError, match="bars_held"):
        evaluate_multileg_execution_policy(
            genome,
            {LEFT: _bars(LEFT, [100.0]), RIGHT: _bars(RIGHT, [100.0])},
            current_legs={LEFT: 0.0, RIGHT: 0.0},
            bars_held=-1,
        )
    with pytest.raises(ValueError, match="missing multi-leg bars"):
        evaluate_multileg_execution_policy(
            genome,
            {LEFT: _bars(LEFT, [100.0])},
            current_legs={LEFT: 0.0, RIGHT: 0.0},
            bars_held=0,
        )
    with pytest.raises(ValueError, match="market bars for every instrument"):
        evaluate_multileg_execution_policy(
            genome,
            {LEFT: _bars(LEFT, [100.0]), RIGHT: ()},
            current_legs={LEFT: 0.0, RIGHT: 0.0},
            bars_held=0,
        )

    unknown = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        {"type": "not_real"},
    )
    with pytest.raises(ValueError, match="unsupported multi-leg exit policy"):
        evaluate_multileg_execution_policy(
            unknown,
            {LEFT: _bars(LEFT, [100.0]), RIGHT: _bars(RIGHT, [100.0])},
            current_legs={LEFT: -1.0, RIGHT: 1.0},
            bars_held=1,
        )


def test_multileg_policy_rejects_missing_or_nonfinite_current_leg_state() -> None:
    genome = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        {"type": "spread_mean_exit", "z_exit": 0.5},
    )
    data = {LEFT: _bars(LEFT, [100.0]), RIGHT: _bars(RIGHT, [100.0])}
    with pytest.raises(ValueError, match="current_legs must match"):
        evaluate_multileg_execution_policy(genome, data, current_legs={LEFT: -1.0}, bars_held=1)
    with pytest.raises(ValueError, match="finite"):
        evaluate_multileg_execution_policy(
            genome,
            data,
            current_legs={LEFT: float("nan"), RIGHT: 1.0},
            bars_held=1,
        )
