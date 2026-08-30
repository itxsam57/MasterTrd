from __future__ import annotations

from typing import Any

from nautilus_trader.examples.strategies.ema_cross import EMACross

from .genome import StrategyGenome
from .risk import RiskAction, RiskLimits, RiskSnapshot
from .risk_runtime import OrderIntent, RiskRuntime


def default_nautilus_risk_limits() -> RiskLimits:
    return RiskLimits(
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


class NautilusRiskMixin:
    risk_runtime: RiskRuntime
    _risk_strategy_id: str

    def _configure_risk_runtime(
        self,
        strategy_id: str,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        self._risk_strategy_id = strategy_id
        self.risk_runtime = risk_runtime or RiskRuntime(default_nautilus_risk_limits())

    def _risk_reference_price(self, instrument_id) -> float:
        return 0.0

    @staticmethod
    def _numeric_quantity(order: Any) -> float:
        quantity = order.quantity
        if hasattr(quantity, "as_double"):
            return float(quantity.as_double())
        return float(quantity)

    def _risk_snapshot_for_order(self, order: Any, intent: OrderIntent) -> RiskSnapshot:
        price = max(0.0, float(self._risk_reference_price(order.instrument_id)))
        return RiskSnapshot(
            order_notional=abs(intent.quantity * price),
            symbol_exposure=0.0,
            portfolio_exposure=0.0,
            daily_pnl=0.0,
            drawdown=0.0,
            orders_last_minute=0,
            leverage=0.0,
            correlated_exposure=0.0,
            spread_bps=0.0,
            realized_volatility=0.0,
            venue_healthy=True,
            api_error_rate=0.0,
            api_latency_ms=0.0,
            reconciliation_age_seconds=0.0,
        )

    def _risk_intent_for_order(self, order: Any) -> OrderIntent:
        instrument_id = order.instrument_id
        side_value = getattr(order, "side", getattr(order, "order_side", "UNKNOWN"))
        order_type = getattr(order, "order_type", "UNKNOWN")
        return OrderIntent(
            strategy_id=self._risk_strategy_id,
            symbol=instrument_id.value,
            venue=instrument_id.venue.value,
            side=getattr(side_value, "name", str(side_value)),
            quantity=self._numeric_quantity(order),
            order_type=getattr(order_type, "name", str(order_type)),
        )

    def submit_order(self, order: Any, *args: Any, **kwargs: Any):
        intent = self._risk_intent_for_order(order)
        snapshot = self._risk_snapshot_for_order(order, intent)
        decision = self.risk_runtime.check_order(intent, snapshot)
        if decision.action is not RiskAction.ALLOW:
            logger = getattr(self, "log", None)
            if logger is not None:
                logger.warning(f"Risk rejected order: {decision.action} {decision.reason}")
            return None
        return super().submit_order(order, *args, **kwargs)


class RiskManagedEMACross(NautilusRiskMixin, EMACross):
    def __init__(
        self,
        *,
        config,
        genome: StrategyGenome,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config=config)
        self.genome = genome
        self._risk_last_price = 0.0
        self._configure_risk_runtime(genome.strategy_id, risk_runtime)

    def on_bar(self, bar) -> None:
        self._risk_last_price = float(bar.close.as_double())
        super().on_bar(bar)

    def _risk_reference_price(self, instrument_id) -> float:
        return self._risk_last_price
