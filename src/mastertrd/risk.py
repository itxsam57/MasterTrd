from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskAction(StrEnum):
    ALLOW = "ALLOW"
    BLOCK_ORDER = "BLOCK_ORDER"
    KILL_STRATEGY = "KILL_STRATEGY"
    KILL_SYMBOL = "KILL_SYMBOL"
    KILL_VENUE = "KILL_VENUE"
    KILL_PORTFOLIO = "KILL_PORTFOLIO"
    KILL_SYSTEM = "KILL_SYSTEM"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_order_notional: float
    max_symbol_exposure: float
    max_portfolio_exposure: float
    max_daily_loss: float
    max_drawdown: float
    max_orders_per_minute: int
    max_leverage: float = 1_000_000_000.0
    max_correlated_exposure: float = 1e18
    max_spread_bps: float = 1_000_000_000.0
    max_realized_volatility: float = 1_000_000_000.0
    duplicate_order_window_seconds: float = 0.0
    max_api_error_rate: float = 1.0
    max_api_latency_ms: float = 1_000_000_000.0
    max_reconciliation_age_seconds: float = 1_000_000_000.0

    def __post_init__(self) -> None:
        numeric = (
            self.max_order_notional,
            self.max_symbol_exposure,
            self.max_portfolio_exposure,
            self.max_daily_loss,
            self.max_drawdown,
            self.max_leverage,
            self.max_correlated_exposure,
            self.max_spread_bps,
            self.max_realized_volatility,
            self.duplicate_order_window_seconds,
            self.max_api_latency_ms,
            self.max_reconciliation_age_seconds,
        )
        if min(float(value) for value in numeric) < 0:
            raise ValueError("risk limits cannot be negative")
        if self.max_orders_per_minute <= 0:
            raise ValueError("max_orders_per_minute must be positive")
        if self.max_leverage <= 0:
            raise ValueError("max_leverage must be positive")
        if not 0.0 <= float(self.max_api_error_rate) <= 1.0:
            raise ValueError("max_api_error_rate must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    order_notional: float
    symbol_exposure: float
    portfolio_exposure: float
    daily_pnl: float
    drawdown: float
    orders_last_minute: int
    data_stale: bool = False
    reconciliation_ok: bool = True
    emergency_stop: bool = False
    leverage: float = 0.0
    correlated_exposure: float = 0.0
    spread_bps: float = 0.0
    realized_volatility: float = 0.0
    duplicate_order: bool = False
    venue_healthy: bool = True
    api_error_rate: float = 0.0
    api_latency_ms: float = 0.0
    reconciliation_age_seconds: float = 0.0


def evaluate_risk(limits: RiskLimits, s: RiskSnapshot) -> RiskAction:
    if (
        s.emergency_stop
        or s.data_stale
        or not s.reconciliation_ok
        or not s.venue_healthy
        or s.api_error_rate > limits.max_api_error_rate
        or s.api_latency_ms > limits.max_api_latency_ms
        or s.reconciliation_age_seconds > limits.max_reconciliation_age_seconds
    ):
        return RiskAction.KILL_SYSTEM
    if s.daily_pnl <= -limits.max_daily_loss or s.drawdown >= limits.max_drawdown:
        return RiskAction.KILL_STRATEGY
    if s.duplicate_order:
        return RiskAction.BLOCK_ORDER
    if s.orders_last_minute >= limits.max_orders_per_minute:
        return RiskAction.BLOCK_ORDER
    if s.order_notional > limits.max_order_notional:
        return RiskAction.BLOCK_ORDER
    if s.symbol_exposure + s.order_notional > limits.max_symbol_exposure:
        return RiskAction.BLOCK_ORDER
    if s.portfolio_exposure + s.order_notional > limits.max_portfolio_exposure:
        return RiskAction.BLOCK_ORDER
    if s.leverage > limits.max_leverage:
        return RiskAction.BLOCK_ORDER
    if s.correlated_exposure > limits.max_correlated_exposure:
        return RiskAction.BLOCK_ORDER
    if s.spread_bps > limits.max_spread_bps:
        return RiskAction.BLOCK_ORDER
    if s.realized_volatility > limits.max_realized_volatility:
        return RiskAction.BLOCK_ORDER
    return RiskAction.ALLOW
