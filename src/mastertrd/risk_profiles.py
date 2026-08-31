from __future__ import annotations

from .risk import RiskLimits
from .risk_runtime import RiskRuntime


def build_research_backtest_risk_runtime() -> RiskRuntime:
    """Return an explicitly requested risk runtime for historical simulation only.

    The limits are intentionally broad so historical validation measures strategy
    behavior rather than a production capital policy, but the runtime still owns
    duplicate/rate/health decisions and every submitted order still passes through
    the same risk hook. Production PAPER/DEMO/TESTNET/LIVE orchestration must inject
    its own stricter runtime and must never rely on this profile implicitly.
    """
    return RiskRuntime(
        RiskLimits(
            max_order_notional=1e12,
            max_symbol_exposure=1e12,
            max_portfolio_exposure=1e12,
            max_daily_loss=1e12,
            max_drawdown=1.0,
            max_orders_per_minute=1_000_000,
            max_leverage=1_000_000.0,
            max_correlated_exposure=1e12,
            max_spread_bps=1_000_000.0,
            max_realized_volatility=1_000_000.0,
            duplicate_order_window_seconds=0.0,
            max_api_error_rate=1.0,
            max_api_latency_ms=1_000_000_000.0,
            max_reconciliation_age_seconds=1_000_000_000.0,
        )
    )
