import pytest

from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.research.generator import generate_candidate
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def test_generated_trend_candidate_compiles_with_explicit_research_trade_size():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from mastertrd.nautilus_bar_strategy import GeneratedBarStrategy

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

    assert isinstance(strategy, GeneratedBarStrategy)
    assert strategy.config.instrument_id == instrument.id
    fast = int(candidate.entry.get("fast_period", candidate.entry.get("fast")))
    slow = int(candidate.entry.get("slow_period", candidate.entry.get("slow")))
    assert fast < slow
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
    unsafe = replace(candidate, exit={"type": "unimplemented_exit"})

    with pytest.raises(ValueError, match="unsupported exit"):
        compile_genome_to_nautilus(
            unsafe,
            instrument=instrument,
            trade_size_override="0.01000",
            risk_runtime=build_research_backtest_risk_runtime(),
        )
