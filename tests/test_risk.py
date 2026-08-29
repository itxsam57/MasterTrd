from mastertrd.risk import RiskAction, RiskLimits, RiskSnapshot, evaluate_risk

LIMITS = RiskLimits(100, 200, 500, 50, 0.20, 10)


def snap(**changes):
    values = dict(order_notional=10, symbol_exposure=20, portfolio_exposure=100, daily_pnl=0, drawdown=0.01, orders_last_minute=0)
    values.update(changes)
    return RiskSnapshot(**values)


def test_normal_order_allowed():
    assert evaluate_risk(LIMITS, snap()) is RiskAction.ALLOW


def test_stale_data_kills_system():
    assert evaluate_risk(LIMITS, snap(data_stale=True)) is RiskAction.KILL_SYSTEM


def test_daily_loss_kills_strategy():
    assert evaluate_risk(LIMITS, snap(daily_pnl=-51)) is RiskAction.KILL_STRATEGY


def test_exposure_blocks_order():
    assert evaluate_risk(LIMITS, snap(symbol_exposure=195, order_notional=10)) is RiskAction.BLOCK_ORDER
