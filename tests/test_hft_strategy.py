from __future__ import annotations

from dataclasses import replace

import pytest

import mastertrd.nautilus_strategy as nautilus_strategy
from mastertrd.execution_signals import SignalDirection
from mastertrd.research.generator import generate_candidate
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


HFT_FAMILIES = (
    "scalping",
    "grid",
    "market_making",
    "order_book",
    "cross_venue_arb",
)


@pytest.mark.parametrize("family", HFT_FAMILIES)
def test_hft_family_compiles_to_dedicated_nautilus_specialist(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    compiler = getattr(nautilus_strategy, "compile_hft_genome_to_nautilus", None)
    assert callable(compiler), "dedicated HFT Nautilus compiler is required"

    eth = TestInstrumentProvider.ethusdt_binance()
    instruments = {eth.id.value: eth}
    genome_instruments = (eth.id.value,)
    if family == "cross_venue_arb":
        btc = TestInstrumentProvider.btcusdt_binance()
        instruments[btc.id.value] = btc
        genome_instruments = (eth.id.value, btc.id.value)

    genome = generate_candidate(family=family, instruments=genome_instruments, seed=31)
    strategy = compiler(
        genome,
        instruments=instruments,
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    from mastertrd.hft_strategy import GeneratedHftStrategy

    assert isinstance(strategy, GeneratedHftStrategy)
    assert strategy.genome.genome_hash == genome.genome_hash
    assert tuple(item.value for item in strategy.config.instrument_ids) == genome.instruments


def test_hft_compiler_requires_explicit_risk_runtime() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    compiler = getattr(nautilus_strategy, "compile_hft_genome_to_nautilus", None)
    assert callable(compiler), "dedicated HFT Nautilus compiler is required"

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(
        family="scalping",
        instruments=(instrument.id.value,),
        seed=37,
    )

    with pytest.raises(ValueError, match="risk_runtime"):
        compiler(
            genome,
            instruments={instrument.id.value: instrument},
            trade_size_override="0.10",
            risk_runtime=None,
        )


@pytest.mark.parametrize("family", HFT_FAMILIES)
def test_hft_compiler_rejects_bar_fallback(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    eth = TestInstrumentProvider.ethusdt_binance()
    instruments = {eth.id.value: eth}
    genome_instruments = (eth.id.value,)
    if family == "cross_venue_arb":
        btc = TestInstrumentProvider.btcusdt_binance()
        instruments[btc.id.value] = btc
        genome_instruments = (eth.id.value, btc.id.value)
    genome = replace(
        generate_candidate(family=family, instruments=genome_instruments, seed=41),
        data_requirements=("BAR",),
    )

    with pytest.raises(ValueError, match="requires (TICK|L2) market data"):
        nautilus_strategy.compile_hft_genome_to_nautilus(
            genome,
            instruments=instruments,
            trade_size_override="0.10",
            risk_runtime=build_research_backtest_risk_runtime(),
        )


def _book(
    instrument_id: str,
    *,
    bid: float,
    ask: float,
    bid_size: float = 10.0,
    ask_size: float = 10.0,
    history: tuple[float, ...] = (),
    inventory: float = 0.0,
):
    from mastertrd.hft_strategy import HftBookState

    return HftBookState(
        instrument_id=instrument_id,
        bid_price=bid,
        ask_price=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        tick_size=0.1,
        mid_history=history,
        inventory=inventory,
    )


def test_scalping_uses_tick_momentum_and_spread_filter() -> None:
    from mastertrd.hft_strategy import evaluate_hft_entry_intents

    instrument_id = "ETHUSDT.BINANCE"
    genome = replace(
        generate_candidate(family="scalping", instruments=(instrument_id,), seed=43),
        entry={"type": "micro_momentum", "ticks": 3},
        filters={"spread_max_ticks": 3},
    )
    state = _book(
        instrument_id,
        bid=100.9,
        ask=101.0,
        history=(100.0, 100.3, 100.6, 100.95),
    )

    intents = evaluate_hft_entry_intents(genome, {instrument_id: state})

    assert len(intents) == 1
    assert intents[0].instrument_id == instrument_id
    assert intents[0].direction is SignalDirection.LONG
    assert intents[0].price is None
    assert intents[0].post_only is False
    assert intents[0].reason == "micro_momentum"

    wide = replace(state, bid_price=100.0, ask_price=101.0)
    assert evaluate_hft_entry_intents(genome, {instrument_id: wide}) == ()


def test_grid_emits_symmetric_post_only_levels() -> None:
    from mastertrd.hft_strategy import evaluate_hft_entry_intents

    instrument_id = "ETHUSDT.BINANCE"
    genome = replace(
        generate_candidate(family="grid", instruments=(instrument_id,), seed=47),
        entry={"type": "dynamic_grid", "levels": 3, "spacing_bps": 10},
    )
    state = _book(instrument_id, bid=99.9, ask=100.1)

    intents = evaluate_hft_entry_intents(genome, {instrument_id: state})

    assert len(intents) == 6
    buys = [intent for intent in intents if intent.direction is SignalDirection.LONG]
    sells = [intent for intent in intents if intent.direction is SignalDirection.SHORT]
    assert len(buys) == len(sells) == 3
    assert all(intent.post_only and intent.price is not None for intent in intents)
    assert max(intent.price for intent in buys) < state.midpoint
    assert min(intent.price for intent in sells) > state.midpoint


def test_market_making_emits_two_sided_inventory_skew_quotes() -> None:
    from mastertrd.hft_strategy import evaluate_hft_entry_intents

    instrument_id = "ETHUSDT.BINANCE"
    genome = replace(
        generate_candidate(family="market_making", instruments=(instrument_id,), seed=53),
        entry={"type": "inventory_skew_mm", "half_spread_bps": 10},
    )
    neutral = _book(instrument_id, bid=99.9, ask=100.1)
    long_inventory = replace(neutral, inventory=0.5)

    neutral_intents = evaluate_hft_entry_intents(genome, {instrument_id: neutral})
    skewed_intents = evaluate_hft_entry_intents(genome, {instrument_id: long_inventory})

    assert {intent.direction for intent in neutral_intents} == {
        SignalDirection.LONG,
        SignalDirection.SHORT,
    }
    assert all(intent.post_only for intent in neutral_intents)
    neutral_buy = next(intent for intent in neutral_intents if intent.direction is SignalDirection.LONG)
    skewed_buy = next(intent for intent in skewed_intents if intent.direction is SignalDirection.LONG)
    assert skewed_buy.price < neutral_buy.price


def test_order_book_imbalance_emits_directional_market_intent() -> None:
    from mastertrd.hft_strategy import evaluate_hft_entry_intents

    instrument_id = "ETHUSDT.BINANCE"
    genome = replace(
        generate_candidate(family="order_book", instruments=(instrument_id,), seed=59),
        entry={"type": "order_book_imbalance", "levels": 5, "threshold": 0.20},
    )
    state = _book(instrument_id, bid=99.9, ask=100.1, bid_size=90.0, ask_size=10.0)

    intents = evaluate_hft_entry_intents(genome, {instrument_id: state})

    assert len(intents) == 1
    assert intents[0].direction is SignalDirection.LONG
    assert intents[0].price is None
    assert intents[0].reason == "order_book_imbalance"


def test_cross_venue_spread_emits_atomic_hedge_pair() -> None:
    from mastertrd.hft_strategy import evaluate_hft_entry_intents

    left = "ETHUSDT.BINANCE"
    right = "ETHUSDT.BINANCE-ALT"
    genome = replace(
        generate_candidate(family="cross_venue_arb", instruments=(left, right), seed=61),
        entry={"type": "cross_venue_spread", "min_edge_bps": 20},
    )
    states = {
        left: _book(left, bid=99.9, ask=100.1),
        right: _book(right, bid=100.9, ask=101.1),
    }

    intents = evaluate_hft_entry_intents(genome, states)

    assert len(intents) == 2
    by_id = {intent.instrument_id: intent for intent in intents}
    assert by_id[left].direction is SignalDirection.LONG
    assert by_id[right].direction is SignalDirection.SHORT
    assert all(intent.price is None for intent in intents)
    assert all(intent.reason == "cross_venue_spread" for intent in intents)


def test_hft_runtime_passes_real_elapsed_milliseconds_to_exit_policy(monkeypatch) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    import mastertrd.hft_strategy as hft_strategy
    from mastertrd.execution_policy import ExecutionDecision

    instrument = TestInstrumentProvider.ethusdt_binance()
    instrument_id = instrument.id.value
    genome = replace(
        generate_candidate(family="market_making", instruments=(instrument_id,), seed=71),
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
    strategy = nautilus_strategy.compile_hft_genome_to_nautilus(
        genome,
        instruments={instrument_id: instrument},
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    strategy.instruments[instrument_id] = instrument
    strategy._positions[instrument_id] = hft_strategy._OpenHftPosition(
        direction=SignalDirection.LONG,
        entry_price=100.0,
        signed_qty=0.05,
        opened_timestamp_ns=1_000_000_000,
    )
    strategy._states[instrument_id] = hft_strategy.HftBookState(
        instrument_id=instrument_id,
        bid_price=99.9,
        ask_price=100.1,
        bid_size=10.0,
        ask_size=10.0,
        tick_size=0.1,
        inventory=0.05,
        timestamp_ns=3_000_000_000,
    )
    captured = {}

    def fake_policy(candidate, state):
        captured["elapsed_ms"] = state.elapsed_ms
        return ExecutionDecision(state.direction, "hold_test", False)

    monkeypatch.setattr(hft_strategy, "evaluate_hft_execution_policy", fake_policy)

    assert strategy._evaluate_open_position_exit(instrument_id) is False
    assert captured["elapsed_ms"] == 2000.0
