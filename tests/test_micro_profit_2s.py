from __future__ import annotations

from dataclasses import replace

from mastertrd.execution_signals import SignalDirection
from mastertrd.hft_strategy import HftBookState, evaluate_hft_entry_intents
from mastertrd.research.generator import generate_candidate


def _candidate():
    instrument_id = "ETHUSDT.BINANCE"
    return replace(
        generate_candidate(family="market_making", instruments=(instrument_id,), seed=211),
        entry={
            "type": "micro_profit_2s",
            "levels": 1,
            "imbalance_threshold": 0.10,
            "target_net_usd": 0.01,
            "maker_fee_bps": 1.0,
            "slippage_bps": 0.5,
            "max_quote_notional_usd": 100.0,
            "inventory_skew_bps": 1.0,
        },
        exit={"type": "micro_profit_timeout", "timeout_ms": 2000, "max_inventory": 0.10},
        filters={"spread_max_bps": 25.0},
        allow_short=True,
    )


def _viable_book(instrument_id: str) -> HftBookState:
    return HftBookState(
        instrument_id=instrument_id,
        bid_price=100.00,
        ask_price=100.20,
        bid_size=30.0,
        ask_size=10.0,
        tick_size=0.01,
        inventory=0.0,
    )


def test_micro_profit_2s_emits_post_only_quotes_only_when_cost_adjusted_edge_can_make_one_cent() -> None:
    genome = _candidate()
    instrument_id = genome.instruments[0]
    viable = _viable_book(instrument_id)

    intents = evaluate_hft_entry_intents(genome, {instrument_id: viable})

    assert {intent.direction for intent in intents} == {
        SignalDirection.LONG,
        SignalDirection.SHORT,
    }
    assert all(intent.post_only for intent in intents)
    assert all(intent.reason == "micro_profit_2s" for intent in intents)
    assert all(intent.price is not None for intent in intents)
    assert all(intent.quantity_weight > 0.0 for intent in intents)
    bid = next(intent for intent in intents if intent.direction is SignalDirection.LONG)
    ask = next(intent for intent in intents if intent.direction is SignalDirection.SHORT)
    assert bid.price <= viable.bid_price
    assert ask.price >= viable.ask_price

    too_tight = replace(viable, bid_price=100.09, ask_price=100.11)
    assert evaluate_hft_entry_intents(genome, {instrument_id: too_tight}) == ()


def test_micro_profit_2s_intent_carries_absolute_notional_that_meets_target_without_trade_size_assumptions() -> None:
    genome = _candidate()
    instrument_id = genome.instruments[0]
    state = _viable_book(instrument_id)

    intents = evaluate_hft_entry_intents(genome, {instrument_id: state})

    gross_edge_per_unit = state.ask_price - state.bid_price
    round_trip_cost_per_unit = state.midpoint * 2.0 * (
        genome.entry["maker_fee_bps"] + genome.entry["slippage_bps"]
    ) / 10_000.0
    net_edge_per_unit = gross_edge_per_unit - round_trip_cost_per_unit
    for intent in intents:
        assert intent.notional_usd is not None
        assert 0.0 < intent.notional_usd <= genome.entry["max_quote_notional_usd"]
        quantity = intent.notional_usd / state.midpoint
        modeled_net_usd = quantity * net_edge_per_unit
        assert modeled_net_usd >= genome.entry["target_net_usd"]
        assert modeled_net_usd < genome.entry["target_net_usd"] + 1e-9
