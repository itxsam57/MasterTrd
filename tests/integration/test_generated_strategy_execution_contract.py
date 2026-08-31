import pytest

from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.research.generator import generate_candidate
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def test_generated_trend_candidate_compiles_with_explicit_research_trade_size():
    from nautilus_trader.examples.strategies.ema_cross import EMACross
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = generate_candidate(
        family="trend",
        instruments=(instrument.id.value,),
        seed=42,
    )

    strategy = compile_genome_to_nautilus(
        candidate,
        instrument=instrument,
        trade_size_override="0.01000",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    assert isinstance(strategy, EMACross)
    assert strategy.config.instrument_id == instrument.id
    assert strategy.config.fast_ema_period < strategy.config.slow_ema_period
    assert str(strategy.config.trade_size) == "0.01000"


def test_generated_candidate_trade_size_must_be_explicit_until_equity_sizing_exists():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = generate_candidate(
        family="trend",
        instruments=(instrument.id.value,),
        seed=7,
    )

    with pytest.raises(ValueError, match="trade_size"):
        compile_genome_to_nautilus(
            candidate,
            instrument=instrument,
            risk_runtime=build_research_backtest_risk_runtime(),
        )


def test_trade_size_override_cannot_hide_an_unsupported_exit_semantic():
    from dataclasses import replace
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = generate_candidate(
        family="trend",
        instruments=(instrument.id.value,),
        seed=9,
    )
    unsafe = replace(candidate, exit={"type": "atr_bracket", "stop_atr": 2.0, "target_atr": 4.0})

    with pytest.raises(ValueError, match="exit"):
        compile_genome_to_nautilus(
            unsafe,
            instrument=instrument,
            trade_size_override="0.01000",
            risk_runtime=build_research_backtest_risk_runtime(),
        )
