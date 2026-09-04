from __future__ import annotations

from typing import Any

from nautilus_trader.examples.strategies.ema_cross import EMACross

from .genome import StrategyGenome
from .risk import RiskAction, RiskSnapshot
from .risk_runtime import OrderIntent, RiskRuntime


class NautilusRiskMixin:
    risk_runtime: RiskRuntime
    _risk_strategy_id: str

    def _configure_risk_runtime(
        self,
        strategy_id: str,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        if risk_runtime is None:
            raise ValueError("risk_runtime is required for risk-managed Nautilus strategies")
        self._risk_strategy_id = strategy_id
        self.risk_runtime = risk_runtime
        self._risk_orders_attempted = 0
        self._risk_orders_allowed = 0
        self._risk_orders_rejected = 0
        self._risk_last_rejection: str | None = None
        self._risk_realized_trade_records: list[tuple[tuple[str, int, int], float]] = []
        self._risk_realized_trade_keys: set[tuple[str, int, int]] = set()

    def _risk_reference_price(self, instrument_id) -> float:
        return 0.0

    @staticmethod
    def _numeric_quantity(order: Any) -> float:
        quantity = order.quantity
        if hasattr(quantity, "as_double"):
            return float(quantity.as_double())
        return float(quantity)

    def _risk_snapshot_for_order(self, order: Any, intent: OrderIntent) -> RiskSnapshot:
        price = float(self._risk_reference_price(order.instrument_id))
        return self.risk_runtime.snapshot_for_order(intent, reference_price=price)

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

    def _record_position_closed(self, event: Any) -> None:
        key = (str(event.position_id), int(event.ts_opened), int(event.ts_closed))
        if key in self._risk_realized_trade_keys:
            return
        self._risk_realized_trade_keys.add(key)
        self._risk_realized_trade_records.append((key, float(event.realized_return)))

    def realized_trade_records(self) -> tuple[tuple[tuple[str, int, int], float], ...]:
        return tuple(self._risk_realized_trade_records)

    def realized_trade_returns(self) -> tuple[float, ...]:
        return tuple(value for _key, value in self._risk_realized_trade_records)

    def on_position_closed(self, event: Any) -> None:
        self._record_position_closed(event)

    def risk_telemetry(self) -> dict[str, object]:
        return {
            "orders_attempted": int(self._risk_orders_attempted),
            "orders_allowed": int(self._risk_orders_allowed),
            "orders_rejected": int(self._risk_orders_rejected),
            "last_risk_rejection": self._risk_last_rejection,
        }

    def submit_order(self, order: Any, *args: Any, **kwargs: Any):
        self._risk_orders_attempted += 1
        intent = self._risk_intent_for_order(order)
        snapshot = self._risk_snapshot_for_order(order, intent)
        decision = self.risk_runtime.check_order(intent, snapshot)
        if decision.action is not RiskAction.ALLOW:
            self._risk_orders_rejected += 1
            self._risk_last_rejection = f"{decision.action}:{decision.reason}"
            logger = getattr(self, "log", None)
            if logger is not None:
                logger.warning(f"Risk rejected order: {decision.action} {decision.reason}")
            return None
        self._risk_orders_allowed += 1
        self._risk_last_rejection = None
        return super().submit_order(order, *args, **kwargs)


class RiskManagedEMACross(NautilusRiskMixin, EMACross):
    """Legacy compatibility wrapper for tests and non-promotion callers.

    Promotion-grade trend compilation no longer selects Nautilus's bundled EMA
    example strategy; see ``compile_genome_to_nautilus``.
    """

    def __init__(
        self,
        *,
        config,
        genome: StrategyGenome | None = None,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config=config)
        self.genome = genome
        self._risk_last_price = 0.0
        configured_id = getattr(config, "strategy_id", None)
        strategy_id = (
            genome.strategy_id
            if genome is not None
            else str(configured_id or f"nautilus:{config.instrument_id.value}")
        )
        self._configure_risk_runtime(strategy_id, risk_runtime)

    def on_bar(self, bar) -> None:
        self._risk_last_price = float(bar.close.as_double())
        super().on_bar(bar)

    def _risk_reference_price(self, instrument_id) -> float:
        return self._risk_last_price
