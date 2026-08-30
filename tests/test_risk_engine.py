from mastertrd.risk import RiskAction, RiskLimits, RiskSnapshot, evaluate_risk


def _limits():
    return RiskLimits(
        max_order_notional=1_000.0,
        max_symbol_exposure=5_000.0,
        max_portfolio_exposure=10_000.0,
        max_daily_loss=500.0,
        max_drawdown=0.20,
        max_orders_per_minute=10,
        max_leverage=3.0,
        max_correlated_exposure=6_000.0,
        max_spread_bps=25.0,
        max_realized_volatility=0.08,
        duplicate_order_window_seconds=5.0,
        max_api_error_rate=0.10,
        max_api_latency_ms=1_000.0,
        max_reconciliation_age_seconds=30.0,
    )


def _snapshot(**overrides):
    values = dict(
        order_notional=500.0,
        symbol_exposure=1_000.0,
        portfolio_exposure=2_000.0,
        daily_pnl=0.0,
        drawdown=0.05,
        orders_last_minute=1,
        leverage=1.0,
        correlated_exposure=1_500.0,
        spread_bps=5.0,
        realized_volatility=0.02,
        duplicate_order=False,
        venue_healthy=True,
        api_error_rate=0.0,
        api_latency_ms=50.0,
        reconciliation_age_seconds=1.0,
    )
    values.update(overrides)
    return RiskSnapshot(**values)


def test_expanded_risk_engine_allows_healthy_order():
    assert evaluate_risk(_limits(), _snapshot()) is RiskAction.ALLOW


def test_abnormal_spread_volatility_leverage_and_correlation_block_order():
    limits = _limits()
    assert evaluate_risk(limits, _snapshot(spread_bps=30.0)) is RiskAction.BLOCK_ORDER
    assert evaluate_risk(limits, _snapshot(realized_volatility=0.10)) is RiskAction.BLOCK_ORDER
    assert evaluate_risk(limits, _snapshot(leverage=3.5)) is RiskAction.BLOCK_ORDER
    assert evaluate_risk(limits, _snapshot(correlated_exposure=6_500.0)) is RiskAction.BLOCK_ORDER


def test_duplicate_order_is_blocked_and_stale_reconciliation_or_api_degradation_kills_system():
    limits = _limits()
    assert evaluate_risk(limits, _snapshot(duplicate_order=True)) is RiskAction.BLOCK_ORDER
    assert evaluate_risk(limits, _snapshot(reconciliation_age_seconds=31.0)) is RiskAction.KILL_SYSTEM
    assert evaluate_risk(limits, _snapshot(api_error_rate=0.11)) is RiskAction.KILL_SYSTEM
    assert evaluate_risk(limits, _snapshot(api_latency_ms=1_001.0)) is RiskAction.KILL_SYSTEM
    assert evaluate_risk(limits, _snapshot(venue_healthy=False)) is RiskAction.KILL_SYSTEM
