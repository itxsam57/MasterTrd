from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import Bar, BarType, InstrumentId
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy

from .contracts import MarketBar
from .execution_policy import ExecutionDecision, evaluate_multileg_execution_policy
from .execution_signals import SignalDirection
from .genome import StrategyGenome
from .nautilus_risk_hook import NautilusRiskMixin
from .risk_runtime import RiskRuntime


def _finite_decimal(value: object, name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal value") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def calculate_leg_order_delta(
    instrument: object,
    *,
    base_trade_size: Decimal,
    leg_weight: float,
    current_signed_quantity: Decimal,
) -> Decimal:
    """Return the signed order delta needed to reach a weighted leg target.

    The target is normalized through the concrete Nautilus instrument so the
    strategy never invents quantity precision independently of the venue model.
    Positive deltas buy and negative deltas sell.
    """
    base = _finite_decimal(base_trade_size, "base_trade_size")
    if base <= 0:
        raise ValueError("base_trade_size must be positive")
    if not isfinite(float(leg_weight)):
        raise ValueError("leg_weight must be finite")
    weight = Decimal(str(leg_weight))
    current = _finite_decimal(current_signed_quantity, "current_signed_quantity")

    if weight == 0:
        target = Decimal("0")
    else:
        requested = base * abs(weight)
        quantity = instrument.make_qty(requested, round_down=True)
        target_magnitude = quantity.as_decimal()
        if target_magnitude <= 0:
            raise ValueError("weighted leg target rounds to zero for instrument precision")

        minimum = getattr(instrument, "min_quantity", None)
        if minimum is not None and target_magnitude < minimum.as_decimal():
            raise ValueError("weighted leg target is below instrument minimum quantity")
        maximum = getattr(instrument, "max_quantity", None)
        if maximum is not None and target_magnitude > maximum.as_decimal():
            raise ValueError("weighted leg target exceeds instrument maximum quantity")
        target = target_magnitude if weight > 0 else -target_magnitude

    delta = target - current
    if delta == 0:
        return delta

    order_quantity = instrument.make_qty(abs(delta), round_down=True).as_decimal()
    if order_quantity <= 0:
        raise ValueError("leg order delta rounds to zero for instrument precision")
    minimum = getattr(instrument, "min_quantity", None)
    if minimum is not None and order_quantity < minimum.as_decimal():
        raise ValueError("leg order delta is below instrument minimum quantity")
    maximum = getattr(instrument, "max_quantity", None)
    if maximum is not None and order_quantity > maximum.as_decimal():
        raise ValueError("leg order delta exceeds instrument maximum quantity")
    return order_quantity if delta > 0 else -order_quantity


class GeneratedMultiLegStrategyConfig(StrategyConfig):
    instrument_ids: tuple[InstrumentId, ...]
    bar_types: tuple[BarType, ...]
    trade_size: Decimal
    family: str
    genome_hash: str


class GeneratedMultiLegStrategy(NautilusRiskMixin, Strategy):
    def __init__(
        self,
        *,
        config: GeneratedMultiLegStrategyConfig,
        genome: StrategyGenome,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config)
        self.genome = genome
        self._bars: dict[str, list[MarketBar]] = {item.value: [] for item in config.instrument_ids}
        self._instruments: dict[str, object] = {}
        self._last_legs: dict[str, float] = {item.value: 0.0 for item in config.instrument_ids}
        self._bars_held = 0
        self.last_decision = ExecutionDecision(SignalDirection.FLAT, "not_started")
        self._configure_risk_runtime(genome.strategy_id, risk_runtime)

    def on_start(self) -> None:
        for instrument_id, bar_type in zip(self.config.instrument_ids, self.config.bar_types, strict=True):
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"Could not find instrument for {instrument_id}")
                self.stop()
                return
            self._instruments[instrument_id.value] = instrument
            self.subscribe_bars(bar_type)

    def _to_market_bar(self, bar: Bar) -> MarketBar:
        instrument_id = bar.bar_type.instrument_id
        return MarketBar(
            timestamp=datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=timezone.utc),
            venue=instrument_id.venue.value,
            instrument=instrument_id.value,
            timeframe=self.genome.timeframe,
            open=bar.open.as_double(),
            high=bar.high.as_double(),
            low=bar.low.as_double(),
            close=bar.close.as_double(),
            volume=bar.volume.as_double(),
        )

    def _evaluate_policy(self) -> ExecutionDecision:
        return evaluate_multileg_execution_policy(
            self.genome,
            self._bars,
            current_legs=self._last_legs,
            bars_held=self._bars_held,
        )

    def on_bar(self, bar: Bar) -> None:
        instrument_id = bar.bar_type.instrument_id.value
        if instrument_id not in self._bars:
            return
        self._bars[instrument_id].append(self._to_market_bar(bar))
        if any(not values for values in self._bars.values()):
            return

        decision = self._evaluate_policy()
        self.last_decision = decision
        target_legs = {key: float(value) for key, value in decision.legs.items()}
        was_open = any(abs(value) > 0.0 for value in self._last_legs.values())
        target_open = any(abs(value) > 0.0 for value in target_legs.values())

        if target_legs != self._last_legs or decision.rebalance_position:
            self._apply_legs(decision)
        self._last_legs = target_legs

        if not target_open:
            self._bars_held = 0
        elif was_open:
            self._bars_held += 1
        else:
            self._bars_held = 1

    def _risk_reference_price(self, instrument_id) -> float:
        values = self._bars.get(instrument_id.value, ())
        if not values:
            return 0.0
        return float(values[-1].close)

    def _current_signed_quantity(self, instrument_id: InstrumentId) -> Decimal:
        positions = self.cache.positions_open(
            instrument_id=instrument_id,
            strategy_id=self.id,
        )
        return sum(
            (position.signed_decimal_qty() for position in positions),
            Decimal("0"),
        )

    def _apply_legs(self, decision: ExecutionDecision) -> None:
        if not decision.legs:
            return
        ids = {item.value: item for item in self.config.instrument_ids}
        if set(decision.legs) != set(ids):
            raise ValueError("multi-leg decision must target every configured instrument exactly")

        for key, raw_target in decision.legs.items():
            instrument_id = ids[key]
            instrument = self._instruments[key]
            target = float(raw_target)
            if target < 0.0 and not self.genome.allow_short:
                target = 0.0
            current = self._current_signed_quantity(instrument_id)
            delta = calculate_leg_order_delta(
                instrument,
                base_trade_size=self.config.trade_size,
                leg_weight=target,
                current_signed_quantity=current,
            )
            if delta == 0:
                continue
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            self._submit_market(instrument_id, side, abs(delta))

    def _submit_market(
        self,
        instrument_id: InstrumentId,
        side: OrderSide,
        quantity: Decimal,
    ) -> None:
        instrument = self._instruments[instrument_id.value]
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=side,
            quantity=instrument.make_qty(quantity, round_down=True),
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        for instrument_id in self.config.instrument_ids:
            self.close_all_positions(instrument_id)
