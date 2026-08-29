import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_strategy import compile_genome_to_nautilus


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


def test_bar_genome_compiles_to_stable_nautilus_strategy():
    from nautilus_trader.examples.strategies.ema_cross import EMACross
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    strategy = compile_genome_to_nautilus(ema_genome(), instrument=instrument)

    assert isinstance(strategy, EMACross)
    assert strategy.config.instrument_id == instrument.id
    assert strategy.config.fast_ema_period == 3
    assert strategy.config.slow_ema_period == 8
    assert str(strategy.config.trade_size) == "0.10"
    assert strategy.config.request_bars is False
    assert strategy.config.subscribe_trade_ticks is False


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
        compile_genome_to_nautilus(invalid, instrument=TestInstrumentProvider.ethusdt_binance())
