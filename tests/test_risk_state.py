from mastertrd.risk import RiskAction, RiskLimits
from mastertrd.risk_runtime import OrderIntent, RiskRuntime
from mastertrd.risk_state import RiskStateProvider, SimulationRiskStateProvider


def _intent() -> OrderIntent:
    return OrderIntent(
        strategy_id="risk-state-1",
        symbol="ETHUSDT.BINANCE",
        venue="BINANCE",
        side="BUY",
        quantity=0.10,
        order_type="MARKET",
        portfolio_id="P-1",
    )


def _limits() -> RiskLimits:
    return RiskLimits(
        max_order_notional=10_000.0,
        max_symbol_exposure=20_000.0,
        max_portfolio_exposure=50_000.0,
        max_daily_loss=2_000.0,
        max_drawdown=0.25,
        max_orders_per_minute=30,
        max_leverage=4.0,
        max_correlated_exposure=25_000.0,
        max_spread_bps=30.0,
        max_realized_volatility=0.50,
        max_api_error_rate=0.10,
        max_api_latency_ms=1_500.0,
        max_reconciliation_age_seconds=60.0,
    )


def test_risk_state_provider_propagates_owned_execution_state() -> None:
    provider = RiskStateProvider(
        clock=lambda: 1_000.0,
        max_market_age_seconds=5.0,
    )
    provider.update_account_state(
        symbol="ETHUSDT.BINANCE",
        portfolio_id="P-1",
        symbol_exposure=2_500.0,
        portfolio_exposure=8_000.0,
        daily_pnl=-125.0,
        drawdown=0.04,
        leverage=1.7,
        correlated_exposure=6_000.0,
    )
    provider.update_market_state(
        symbol="ETHUSDT.BINANCE",
        spread_bps=12.5,
        realized_volatility=0.35,
        observed_at=998.0,
    )
    provider.update_reconciliation(ok=True, observed_at=997.0)
    provider.update_venue_state(
        venue="BINANCE",
        healthy=True,
        api_error_rate=0.02,
        api_latency_ms=45.0,
    )

    snapshot = provider.snapshot(_intent(), reference_price=2_100.0)

    assert snapshot.order_notional == 210.0
    assert snapshot.symbol_exposure == 2_500.0
    assert snapshot.portfolio_exposure == 8_000.0
    assert snapshot.daily_pnl == -125.0
    assert snapshot.drawdown == 0.04
    assert snapshot.leverage == 1.7
    assert snapshot.correlated_exposure == 6_000.0
    assert snapshot.spread_bps == 12.5
    assert snapshot.realized_volatility == 0.35
    assert snapshot.data_stale is False
    assert snapshot.reconciliation_ok is True
    assert snapshot.reconciliation_age_seconds == 3.0
    assert snapshot.venue_healthy is True
    assert snapshot.api_error_rate == 0.02
    assert snapshot.api_latency_ms == 45.0
    assert snapshot.emergency_stop is False


def test_missing_or_stale_execution_state_fails_closed() -> None:
    intent = _intent()
    provider = RiskStateProvider(
        clock=lambda: 1_000.0,
        max_market_age_seconds=5.0,
    )

    missing = provider.snapshot(intent, reference_price=2_100.0)
    assert missing.emergency_stop is True
    assert missing.data_stale is True
    assert missing.reconciliation_ok is False
    assert missing.venue_healthy is False
    assert RiskRuntime(_limits()).check_order(intent, missing).action is RiskAction.KILL_SYSTEM

    provider.update_account_state(
        symbol=intent.symbol,
        portfolio_id=intent.portfolio_id,
        symbol_exposure=1_000.0,
        portfolio_exposure=2_000.0,
        daily_pnl=25.0,
        drawdown=0.01,
        leverage=1.2,
        correlated_exposure=500.0,
    )
    provider.update_market_state(
        symbol=intent.symbol,
        spread_bps=4.0,
        realized_volatility=0.05,
        observed_at=990.0,
    )
    provider.update_reconciliation(ok=True, observed_at=999.0)
    provider.update_venue_state(
        venue=intent.venue,
        healthy=True,
        api_error_rate=0.0,
        api_latency_ms=20.0,
    )

    stale = provider.snapshot(intent, reference_price=2_100.0)
    assert stale.data_stale is True
    assert stale.emergency_stop is False
    assert RiskRuntime(_limits()).check_order(intent, stale).action is RiskAction.KILL_SYSTEM


def test_backtest_simulation_state_is_explicitly_named() -> None:
    snapshot = SimulationRiskStateProvider().snapshot(_intent(), reference_price=2_100.0)

    assert snapshot.order_notional == 210.0
    assert snapshot.emergency_stop is False
    assert snapshot.data_stale is False
    assert snapshot.reconciliation_ok is True
    assert snapshot.venue_healthy is True
