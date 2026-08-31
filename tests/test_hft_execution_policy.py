from __future__ import annotations

import pytest

from mastertrd.execution_policy import HftPositionState, evaluate_hft_execution_policy
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome


def _genome(family: str, exit_rule: dict) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=f"hft-exit-{family}",
        family=family,
        style=family,
        instruments=("ETHUSDT.BINANCE",),
        timeframe="tick",
        entry={"type": "specialist"},
        exit=exit_rule,
        data_requirements=("L2",),
        allow_short=True,
    )


def _state(**overrides: float | int | SignalDirection) -> HftPositionState:
    values = {
        "direction": SignalDirection.LONG,
        "entry_price": 100.0,
        "current_price": 100.0,
        "tick_size": 0.1,
        "ticks_held": 5,
        "inventory": 0.0,
        "imbalance": 0.2,
        "spread_bps": 10.0,
    }
    values.update(overrides)
    return HftPositionState(**values)


def test_scalping_ticks_or_timeout_closes_on_target_stop_and_timeout() -> None:
    genome = _genome(
        "scalping",
        {"type": "ticks_or_timeout", "stop_ticks": 3, "target_ticks": 5, "max_ticks": 20},
    )

    target = evaluate_hft_execution_policy(genome, _state(current_price=100.5))
    stopped = evaluate_hft_execution_policy(genome, _state(current_price=99.7))
    timeout = evaluate_hft_execution_policy(genome, _state(ticks_held=20))

    assert target.close_position and target.reason == "hft_target_ticks"
    assert stopped.close_position and stopped.reason == "hft_stop_ticks"
    assert timeout.close_position and timeout.reason == "hft_timeout"


@pytest.mark.parametrize("family,kind", (("grid", "inventory_exit"), ("market_making", "inventory_flatten")))
def test_inventory_exit_families_flatten_at_configured_inventory_limit(family: str, kind: str) -> None:
    genome = _genome(family, {"type": kind, "max_inventory": 0.5})

    decision = evaluate_hft_execution_policy(genome, _state(inventory=-0.6))

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "hft_inventory_exit"


def test_order_book_exit_closes_on_imbalance_reversal_or_adverse_ticks() -> None:
    genome = _genome("order_book", {"type": "imbalance_reversal_or_ticks", "ticks": 4})

    reversed_book = evaluate_hft_execution_policy(genome, _state(imbalance=-0.1))
    adverse_move = evaluate_hft_execution_policy(genome, _state(current_price=99.6, imbalance=0.1))

    assert reversed_book.close_position and reversed_book.reason == "hft_imbalance_reversal"
    assert adverse_move.close_position and adverse_move.reason == "hft_adverse_ticks"


def test_cross_venue_spread_convergence_flattens_inside_exit_band() -> None:
    genome = _genome("cross_venue_arb", {"type": "spread_convergence", "exit_bps": 3})

    decision = evaluate_hft_execution_policy(genome, _state(spread_bps=2.0))

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "hft_spread_convergence"


def test_hft_exit_state_fails_closed_on_nonfinite_or_invalid_tick_state() -> None:
    genome = _genome(
        "scalping",
        {"type": "ticks_or_timeout", "stop_ticks": 3, "target_ticks": 5, "max_ticks": 20},
    )
    with pytest.raises(ValueError, match="tick_size"):
        evaluate_hft_execution_policy(genome, _state(tick_size=0.0))
    with pytest.raises(ValueError, match="current_price"):
        evaluate_hft_execution_policy(genome, _state(current_price=float("nan")))
