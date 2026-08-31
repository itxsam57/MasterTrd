from __future__ import annotations

import pytest

import mastertrd.nautilus_strategy as nautilus_strategy
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
