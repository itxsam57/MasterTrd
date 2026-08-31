from __future__ import annotations

import pytest

from mastertrd.nautilus_risk_hook import build_research_nautilus_risk_runtime
from mastertrd.nautilus_strategy import SpecialistPathRequired, compile_genome_to_nautilus
from mastertrd.research.generator import generate_candidate


BAR_FAMILIES = (
    "momentum",
    "breakout",
    "mean_reversion",
    "volatility",
    "swing",
    "position",
)
MULTI_LEG_FAMILIES = (
    "stat_arb",
    "funding_basis",
    "delta_neutral",
    "portfolio",
)
HFT_FAMILIES = (
    "scalping",
    "grid",
    "market_making",
    "order_book",
    "cross_venue_arb",
)


@pytest.mark.parametrize("family", BAR_FAMILIES)
def test_generated_bar_family_compiles(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from mastertrd.nautilus_bar_strategy import GeneratedBarStrategy

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(family=family, instruments=(instrument.id.value,), seed=11)
    risk_runtime = build_research_nautilus_risk_runtime()

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size_override="0.10",
        risk_runtime=risk_runtime,
    )

    assert isinstance(strategy, GeneratedBarStrategy)
    assert strategy.risk_runtime is risk_runtime
    assert strategy.genome.genome_hash == genome.genome_hash
    assert strategy.config.instrument_id == instrument.id


@pytest.mark.parametrize("family", MULTI_LEG_FAMILIES)
def test_generated_multi_leg_family_compiles_with_instrument_map(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from mastertrd.nautilus_multileg_strategy import GeneratedMultiLegStrategy

    eth = TestInstrumentProvider.ethusdt_binance()
    btc = TestInstrumentProvider.btcusdt_binance()
    genome = generate_candidate(
        family=family,
        instruments=(eth.id.value, btc.id.value),
        seed=13,
    )
    risk_runtime = build_research_nautilus_risk_runtime()

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=eth,
        instrument_map={eth.id.value: eth, btc.id.value: btc},
        trade_size_override="0.10",
        risk_runtime=risk_runtime,
    )

    assert isinstance(strategy, GeneratedMultiLegStrategy)
    assert strategy.risk_runtime is risk_runtime
    assert strategy.genome.genome_hash == genome.genome_hash
    assert tuple(item.value for item in strategy.config.instrument_ids) == genome.instruments


def test_options_family_compiles_to_defined_risk_adapter() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from mastertrd.nautilus_options_strategy import GeneratedOptionsStrategy

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(family="options", instruments=(instrument.id.value,), seed=17)
    risk_runtime = build_research_nautilus_risk_runtime()

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size_override="0.10",
        risk_runtime=risk_runtime,
    )

    assert isinstance(strategy, GeneratedOptionsStrategy)
    assert strategy.risk_runtime is risk_runtime
    assert strategy.genome.filters["defined_risk_only"] is True


@pytest.mark.parametrize("family", HFT_FAMILIES)
def test_hft_family_requires_specialist_compiler(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(family=family, instruments=(instrument.id.value,), seed=19)

    with pytest.raises(SpecialistPathRequired, match="specialist HFT path"):
        compile_genome_to_nautilus(genome, instrument=instrument, trade_size_override="0.10")
