from __future__ import annotations

from decimal import Decimal

import pytest

from mastertrd.nautilus_strategy import SpecialistPathRequired, compile_genome_to_nautilus
from mastertrd.research.generator import generate_candidate
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


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


def _option_contract():
    from nautilus_trader.model.enums import AssetClass, OptionKind
    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.model.instruments import OptionContract
    from nautilus_trader.model.objects import Currency, Price, Quantity

    return OptionContract(
        instrument_id=InstrumentId.from_str("AAPL211217C00150000.OPRA"),
        raw_symbol=Symbol("AAPL211217C00150000"),
        asset_class=AssetClass.EQUITY,
        underlying="AAPL",
        option_kind=OptionKind.CALL,
        strike_price=Price.from_str("150.00"),
        currency=Currency.from_str("USD"),
        activation_ns=1,
        expiration_ns=2,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        multiplier=Quantity.from_int(100),
        lot_size=Quantity.from_int(1),
        margin_init=Decimal("0"),
        margin_maint=Decimal("0"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
        exchange="OPRA",
    )


@pytest.mark.parametrize("family", BAR_FAMILIES)
def test_generated_bar_family_compiles(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from mastertrd.nautilus_bar_strategy import GeneratedBarStrategy

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(family=family, instruments=(instrument.id.value,), seed=11)

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    assert isinstance(strategy, GeneratedBarStrategy)
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

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=eth,
        instrument_map={eth.id.value: eth, btc.id.value: btc},
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    assert isinstance(strategy, GeneratedMultiLegStrategy)
    assert strategy.genome.genome_hash == genome.genome_hash
    assert tuple(item.value for item in strategy.config.instrument_ids) == genome.instruments


def test_options_family_rejects_spot_instrument() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(family="options", instruments=(instrument.id.value,), seed=17)

    with pytest.raises(ValueError, match="option-compatible"):
        compile_genome_to_nautilus(
            genome,
            instrument=instrument,
            trade_size_override="0.10",
            risk_runtime=build_research_backtest_risk_runtime(),
        )


def test_options_family_compiles_real_option_to_defined_risk_adapter() -> None:
    from mastertrd.nautilus_options_strategy import GeneratedOptionsStrategy

    instrument = _option_contract()
    genome = generate_candidate(family="options", instruments=(instrument.id.value,), seed=17)

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size_override="1",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    assert isinstance(strategy, GeneratedOptionsStrategy)
    assert strategy.genome.filters["defined_risk_only"] is True
    assert strategy.config.instrument_id == instrument.id


@pytest.mark.parametrize("family", HFT_FAMILIES)
def test_hft_family_requires_specialist_compiler(family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = generate_candidate(family=family, instruments=(instrument.id.value,), seed=19)

    with pytest.raises(SpecialistPathRequired, match="specialist HFT path"):
        compile_genome_to_nautilus(genome, instrument=instrument, trade_size_override="0.10")
