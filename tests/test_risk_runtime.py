from mastertrd.risk import RiskAction, RiskLimits, RiskSnapshot
from mastertrd.risk_profiles import build_research_backtest_risk_runtime
from mastertrd.risk_runtime import KillScope, OrderIntent, RiskRuntime
from mastertrd.risk_state import RiskStateProvider, SimulationRiskStateProvider


def _limits():
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
        max_realized_volatility=0.10,
        duplicate_order_window_seconds=5.0,
        max_api_error_rate=0.10,
        max_api_latency_ms=1_500.0,
        max_reconciliation_age_seconds=60.0,
    )


def _snapshot(**overrides):
    values = dict(
        order_notional=1_000.0,
        symbol_exposure=0.0,
        portfolio_exposure=0.0,
        daily_pnl=0.0,
        drawdown=0.0,
        orders_last_minute=0,
        leverage=1.0,
        correlated_exposure=0.0,
        spread_bps=2.0,
        realized_volatility=0.01,
        duplicate_order=False,
        venue_healthy=True,
        api_error_rate=0.0,
        api_latency_ms=20.0,
        reconciliation_age_seconds=0.0,
    )
    values.update(overrides)
    return RiskSnapshot(**values)


def _intent(**overrides):
    values = dict(
        strategy_id="S-1",
        symbol="ETHUSDT.BINANCE",
        venue="BINANCE",
        side="BUY",
        quantity=0.1,
        order_type="MARKET",
        portfolio_id="P-1",
    )
    values.update(overrides)
    return OrderIntent(**values)


def test_risk_runtime_records_allow_and_blocks_duplicate_inside_window():
    times = iter((100.0, 101.0, 106.1))
    runtime = RiskRuntime(_limits(), monotonic_clock=lambda: next(times))

    first = runtime.check_order(_intent(), _snapshot())
    duplicate = runtime.check_order(_intent(), _snapshot())
    after_window = runtime.check_order(_intent(), _snapshot())

    assert first.action is RiskAction.ALLOW
    assert duplicate.action is RiskAction.BLOCK_ORDER
    assert "duplicate" in duplicate.reason
    assert after_window.action is RiskAction.ALLOW
    assert runtime.allow_count == 2
    assert len(runtime.decisions) == 3


def test_kill_scopes_block_only_matching_intents_and_system_kill_blocks_everything():
    cases = (
        (KillScope.STRATEGY, "S-1", _intent(), RiskAction.KILL_STRATEGY),
        (KillScope.SYMBOL, "ETHUSDT.BINANCE", _intent(), RiskAction.KILL_SYMBOL),
        (KillScope.VENUE, "BINANCE", _intent(), RiskAction.KILL_VENUE),
        (KillScope.PORTFOLIO, "P-1", _intent(), RiskAction.KILL_PORTFOLIO),
    )
    for scope, key, intent, expected in cases:
        runtime = RiskRuntime(_limits())
        runtime.kill(scope, f"manual {scope.value.lower()} stop", key=key)
        denied = runtime.check_order(intent, _snapshot())
        assert denied.action is expected
        assert "manual" in denied.reason

        other = _intent(
            strategy_id="S-2",
            symbol="BTCUSDT.OTHER",
            venue="OTHER",
            portfolio_id="P-2",
        )
        assert runtime.check_order(other, _snapshot()).action is RiskAction.ALLOW

    runtime = RiskRuntime(_limits())
    runtime.kill(KillScope.SYSTEM, "emergency")
    system_denied = runtime.check_order(
        _intent(strategy_id="S-2", symbol="BTCUSDT.OTHER", venue="OTHER", portfolio_id="P-2"),
        _snapshot(),
    )
    assert system_denied.action is RiskAction.KILL_SYSTEM
    assert "emergency" in system_denied.reason


def test_runtime_owned_api_health_and_correlation_snapshots_feed_order_checks():
    runtime = RiskRuntime(_limits())
    runtime.update_api_health(
        venue="BINANCE",
        healthy=False,
        error_rate=0.25,
        latency_ms=2_000.0,
    )
    api_denied = runtime.check_order(_intent(), _snapshot())
    assert api_denied.action is RiskAction.KILL_SYSTEM

    runtime = RiskRuntime(_limits())
    runtime.update_correlated_exposure(portfolio_id="P-1", exposure=30_000.0)
    correlation_denied = runtime.check_order(_intent(), _snapshot())
    assert correlation_denied.action is RiskAction.BLOCK_ORDER


def test_runtime_owns_order_rate_even_when_strategy_snapshot_reports_zero():
    times = iter((100.0, 101.0, 102.0, 161.1))
    limits = RiskLimits(
        max_order_notional=10_000.0,
        max_symbol_exposure=100_000.0,
        max_portfolio_exposure=100_000.0,
        max_daily_loss=2_000.0,
        max_drawdown=0.25,
        max_orders_per_minute=2,
        duplicate_order_window_seconds=0.0,
    )
    runtime = RiskRuntime(limits, monotonic_clock=lambda: next(times))

    assert runtime.check_order(_intent(side="BUY", quantity=0.10), _snapshot()).action is RiskAction.ALLOW
    assert runtime.check_order(_intent(side="BUY", quantity=0.11), _snapshot()).action is RiskAction.ALLOW
    blocked = runtime.check_order(_intent(side="BUY", quantity=0.12), _snapshot())
    assert blocked.action is RiskAction.BLOCK_ORDER
    assert "order" in blocked.reason.lower()

    after_window = runtime.check_order(_intent(side="BUY", quantity=0.13), _snapshot())
    assert after_window.action is RiskAction.ALLOW


def test_runtime_owns_state_provider_and_missing_provider_fails_closed():
    intent = _intent()
    provider = RiskStateProvider(clock=lambda: 1_000.0, max_market_age_seconds=5.0)
    provider.update_account_state(
        symbol=intent.symbol,
        portfolio_id=intent.portfolio_id,
        symbol_exposure=2_500.0,
        portfolio_exposure=8_000.0,
        daily_pnl=-125.0,
        drawdown=0.04,
        leverage=1.7,
        correlated_exposure=6_000.0,
    )
    provider.update_market_state(
        symbol=intent.symbol,
        spread_bps=12.5,
        realized_volatility=0.05,
        observed_at=998.0,
    )
    provider.update_reconciliation(ok=True, observed_at=997.0)
    provider.update_venue_state(
        venue=intent.venue,
        healthy=True,
        api_error_rate=0.02,
        api_latency_ms=45.0,
    )

    runtime = RiskRuntime(_limits(), state_provider=provider)
    owned = runtime.snapshot_for_order(intent, reference_price=2_100.0)
    assert owned.symbol_exposure == 2_500.0
    assert owned.portfolio_exposure == 8_000.0
    assert runtime.check_order(intent, owned).action is RiskAction.ALLOW

    missing_runtime = RiskRuntime(_limits())
    missing = missing_runtime.snapshot_for_order(intent, reference_price=2_100.0)
    assert missing.emergency_stop is True
    assert missing.data_stale is True
    assert missing.reconciliation_ok is False
    assert missing.venue_healthy is False
    assert missing_runtime.check_order(intent, missing).action is RiskAction.KILL_SYSTEM


def test_research_backtest_profile_explicitly_owns_simulation_state() -> None:
    runtime = build_research_backtest_risk_runtime()

    assert isinstance(runtime.state_provider, SimulationRiskStateProvider)
    snapshot = runtime.snapshot_for_order(_intent(), reference_price=2_100.0)
    assert snapshot.emergency_stop is False
    assert snapshot.reconciliation_ok is True
    assert snapshot.venue_healthy is True
