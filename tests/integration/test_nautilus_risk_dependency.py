import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.risk import RiskLimits
from mastertrd.risk_runtime import RiskRuntime


def genome(instrument_id: str) -> StrategyGenome:
    return StrategyGenome(
        strategy_id="risk-required-1",
        family="trend",
        style="day",
        instruments=(instrument_id,),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8},
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )


def explicit_research_risk() -> RiskRuntime:
    return RiskRuntime(
        RiskLimits(
            max_order_notional=1e12,
            max_symbol_exposure=1e12,
            max_portfolio_exposure=1e12,
            max_daily_loss=1e12,
            max_drawdown=1.0,
            max_orders_per_minute=1_000_000,
        )
    )


def test_compiler_refuses_implicit_permissive_risk_runtime():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    with pytest.raises(ValueError, match="risk_runtime is required"):
        compile_genome_to_nautilus(
            genome(instrument.id.value),
            instrument=instrument,
            trade_size="0.1",
        )


def test_compiler_accepts_explicit_risk_runtime_dependency():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    risk = explicit_research_risk()
    strategy = compile_genome_to_nautilus(
        genome(instrument.id.value),
        instrument=instrument,
        trade_size="0.1",
        risk_runtime=risk,
    )
    assert strategy.risk_runtime is risk


def test_direct_risk_managed_strategy_construction_requires_runtime():
    from mastertrd.nautilus_risk_hook import RiskManagedEMACross
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = genome(instrument.id.value)
    compiled = compile_genome_to_nautilus(
        candidate,
        instrument=instrument,
        trade_size="0.1",
        risk_runtime=explicit_research_risk(),
    )

    with pytest.raises(ValueError, match="risk_runtime is required"):
        RiskManagedEMACross(config=compiled.config, genome=candidate)
