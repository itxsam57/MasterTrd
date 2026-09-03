import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def ema_genome(*, family: str = "trend") -> StrategyGenome:
    return StrategyGenome(
        strategy_id="ema-baseline-1",
        family=family,
        style="day",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={
            "kind": "ema_cross",
            "fast_period": 3,
            "slow_period": 8,
            "trade_size": "0.10",
        },
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )


def test_bar_genome_compiles_to_mastertrd_generated_bar_strategy():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from mastertrd.nautilus_bar_strategy import GeneratedBarStrategy

    instrument = TestInstrumentProvider.ethusdt_binance()
    strategy = compile_genome_to_nautilus(
        ema_genome(),
        instrument=instrument,
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    assert isinstance(strategy, GeneratedBarStrategy)
    assert strategy.config.instrument_id == instrument.id
    assert strategy.genome.entry["fast_period"] == 3
    assert strategy.genome.entry["slow_period"] == 8
    assert str(strategy.config.trade_size) == "0.10"
    telemetry = strategy.runtime_telemetry()
    assert telemetry["bars_required"] == 8
    assert telemetry["warmup_remaining"] == 8


def test_compiler_rejects_hft_family_from_generic_nautilus_path():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    with pytest.raises(ValueError, match="specialist HFT path"):
        compile_genome_to_nautilus(
            ema_genome(family="scalping"),
            instrument=TestInstrumentProvider.ethusdt_binance(),
        )


def test_compiler_rejects_invalid_ema_periods():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    genome = ema_genome()
    invalid = StrategyGenome(
        strategy_id=genome.strategy_id,
        family=genome.family,
        style=genome.style,
        instruments=genome.instruments,
        timeframe=genome.timeframe,
        entry={"kind": "ema_cross", "fast_period": 20, "slow_period": 5, "trade_size": "0.10"},
        exit=genome.exit,
        allow_short=genome.allow_short,
    )
    with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
        compile_genome_to_nautilus(
            invalid,
            instrument=TestInstrumentProvider.ethusdt_binance(),
            risk_runtime=build_research_backtest_risk_runtime(),
        )
