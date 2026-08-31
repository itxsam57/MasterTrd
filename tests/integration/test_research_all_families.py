from datetime import datetime, timezone

from mastertrd.contracts import MarketBar
from mastertrd.product_contracts import validate_product_compatibility
from mastertrd.research.generator import family_instrument_sets
from mastertrd.research_brain import (
    ResearchBrainConfig,
    ResearchDataset,
    generate_research_candidates,
)


def test_family_instrument_sets_are_structurally_compatible_with_registered_families():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    btc_spot = TestInstrumentProvider.btcusdt_binance()
    eth_spot = TestInstrumentProvider.ethusdt_binance()
    btc_perp = TestInstrumentProvider.btcusdt_perp_binance()
    option = TestInstrumentProvider.crypto_option()
    bybit_perp = TestInstrumentProvider.xrpusdt_linear_bybit()
    instruments = {
        item.id.value: item
        for item in (btc_spot, eth_spot, btc_perp, option, bybit_perp)
    }
    data_levels = {
        btc_spot.id.value: frozenset({"BAR", "TICK", "L2"}),
        eth_spot.id.value: frozenset({"BAR"}),
        btc_perp.id.value: frozenset({"BAR", "TICK"}),
        option.id.value: frozenset({"BAR"}),
        bybit_perp.id.value: frozenset({"BAR", "TICK", "L2"}),
    }

    trend_sets = family_instrument_sets(
        "trend",
        instruments,
        available_data_levels=data_levels,
    )
    assert (btc_spot.id.value,) in trend_sets
    assert (eth_spot.id.value,) in trend_sets
    assert all(len(items) == 1 for items in trend_sets)
    assert all(option.id.value not in items for items in trend_sets)

    stat_arb_sets = family_instrument_sets(
        "stat_arb",
        instruments,
        available_data_levels=data_levels,
    )
    assert stat_arb_sets
    assert all(len(items) == 2 for items in stat_arb_sets)
    assert all(option.id.value not in items for items in stat_arb_sets)

    funding_sets = family_instrument_sets(
        "funding_basis",
        instruments,
        available_data_levels=data_levels,
    )
    assert (btc_spot.id.value, btc_perp.id.value) in funding_sets
    assert all(len(items) == 2 for items in funding_sets)

    portfolio_sets = family_instrument_sets(
        "portfolio",
        instruments,
        available_data_levels=data_levels,
    )
    assert portfolio_sets
    assert all(len(items) >= 2 for items in portfolio_sets)
    assert all(option.id.value not in items for items in portfolio_sets)

    options_sets = family_instrument_sets(
        "options",
        instruments,
        available_data_levels=data_levels,
    )
    assert options_sets == ((option.id.value,),)

    scalping_sets = family_instrument_sets(
        "scalping",
        instruments,
        available_data_levels=data_levels,
    )
    assert (btc_spot.id.value,) in scalping_sets
    assert (btc_perp.id.value,) in scalping_sets
    assert (eth_spot.id.value,) not in scalping_sets

    order_book_sets = family_instrument_sets(
        "order_book",
        instruments,
        available_data_levels=data_levels,
    )
    assert order_book_sets == (
        (btc_spot.id.value,),
        (bybit_perp.id.value,),
    )

    cross_venue_sets = family_instrument_sets(
        "cross_venue_arb",
        instruments,
        available_data_levels=data_levels,
    )
    assert cross_venue_sets
    assert all(len(items) == 2 for items in cross_venue_sets)
    for left, right in cross_venue_sets:
        assert instruments[left].id.venue != instruments[right].id.venue
        assert "TICK" in data_levels[left]
        assert "TICK" in data_levels[right]


def test_family_instrument_sets_fail_closed_when_required_data_or_products_are_missing():
    import pytest
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    btc = TestInstrumentProvider.btcusdt_binance()
    instruments = {btc.id.value: btc}

    assert family_instrument_sets(
        "trend",
        instruments,
        available_data_levels={btc.id.value: frozenset({"BAR"})},
    ) == ((btc.id.value,),)
    assert family_instrument_sets(
        "market_making",
        instruments,
        available_data_levels={btc.id.value: frozenset({"BAR", "TICK"})},
    ) == ()
    assert family_instrument_sets(
        "options",
        instruments,
        available_data_levels={btc.id.value: frozenset({"BAR"})},
    ) == ()
    assert family_instrument_sets(
        "stat_arb",
        instruments,
        available_data_levels={btc.id.value: frozenset({"BAR"})},
    ) == ()

    with pytest.raises(ValueError, match="metadata key"):
        family_instrument_sets(
            "trend",
            {"WRONG.BINANCE": btc},
            available_data_levels={"WRONG.BINANCE": frozenset({"BAR"})},
        )


def _bar(instrument) -> MarketBar:
    return MarketBar(
        venue=str(instrument.id.venue),
        instrument=str(instrument.raw_symbol),
        timeframe="1h",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1.0,
    )


def test_research_brain_candidate_generation_consumes_family_aware_universes():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    btc_spot = TestInstrumentProvider.btcusdt_binance()
    eth_spot = TestInstrumentProvider.ethusdt_binance()
    btc_perp = TestInstrumentProvider.btcusdt_perp_binance()
    option = TestInstrumentProvider.crypto_option()
    bybit_perp = TestInstrumentProvider.xrpusdt_linear_bybit()
    metadata = {
        item.id.value: item
        for item in (btc_spot, eth_spot, btc_perp, option, bybit_perp)
    }
    data_levels = {
        btc_spot.id.value: frozenset({"BAR", "TICK", "L2"}),
        eth_spot.id.value: frozenset({"BAR"}),
        btc_perp.id.value: frozenset({"BAR", "TICK"}),
        option.id.value: frozenset({"BAR"}),
        bybit_perp.id.value: frozenset({"BAR", "TICK", "L2"}),
    }
    config = ResearchBrainConfig(
        families=("stat_arb", "options", "order_book", "cross_venue_arb"),
        instruments=tuple(metadata),
        seed_start=7,
        seed_stop=8,
        screening_min_return=99.0,
        optimization_trials=1,
        evolution_generations=1,
        evolution_population=2,
        validation_budget=1,
        paper_queue_cap=0,
    )
    dataset = ResearchDataset(
        dataset_hash="family-aware-source-v1",
        bars_by_instrument={key: (_bar(instrument),) for key, instrument in metadata.items()},
        nautilus_instruments=metadata,
        available_data_levels=data_levels,
    )

    batch = generate_research_candidates(config, dataset)

    assert batch.blockers == ()
    candidates_by_family = {
        family: tuple(candidate for candidate in batch.candidates if candidate.family == family)
        for family in config.families
    }
    assert all(candidates_by_family[family] for family in config.families)
    assert all(len(candidate.instruments) == 2 for candidate in candidates_by_family["stat_arb"])
    assert all(
        candidate.instruments == (option.id.value,)
        for candidate in candidates_by_family["options"]
    )
    assert all(
        candidate.data_requirements == ("L2",)
        for candidate in candidates_by_family["order_book"]
    )
    for candidate in candidates_by_family["cross_venue_arb"]:
        left, right = candidate.instruments
        assert metadata[left].id.venue != metadata[right].id.venue

    for candidate in batch.candidates:
        validate_product_compatibility(
            candidate,
            {instrument_id: metadata[instrument_id] for instrument_id in candidate.instruments},
        )
