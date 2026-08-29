from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RiskAction(StrEnum):
    ALLOW = "ALLOW"
    BLOCK_ORDER = "BLOCK_ORDER"
    KILL_STRATEGY = "KILL_STRATEGY"
    KILL_SYSTEM = "KILL_SYSTEM"


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_order_notional: float
    max_symbol_exposure: float
    max_portfolio_exposure: float
    max_daily_loss: float
    max_drawdown: float
    max_orders_per_minute: int

    def __post_init__(self) -> None:
        if min(self.max_order_notional, self.max_symbol_exposure, self.max_portfolio_exposure, self.max_daily_loss, self.max_drawdown) < 0:
            raise ValueError("risk limits cannot be negative")
        if self.max_orders_per_minute <= 0:
            raise ValueError("max_orders_per_minute must be positive")


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


def evaluate_risk(limits: RiskLimits, s: RiskSnapshot) -> RiskAction:
    if s.emergency_stop or s.data_stale or not s.reconciliation_ok:
        return RiskAction.KILL_SYSTEM
    if s.daily_pnl <= -limits.max_daily_loss or s.drawdown >= limits.max_drawdown:
        return RiskAction.KILL_STRATEGY
    if s.orders_last_minute >= limits.max_orders_per_minute:
        return RiskAction.BLOCK_ORDER
    if s.order_notional > limits.max_order_notional:
        return RiskAction.BLOCK_ORDER
    if s.symbol_exposure + s.order_notional > limits.max_symbol_exposure:
        return RiskAction.BLOCK_ORDER
    if s.portfolio_exposure + s.order_notional > limits.max_portfolio_exposure:
        return RiskAction.BLOCK_ORDER
    return RiskAction.ALLOW
