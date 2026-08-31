from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

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

    def _apply_legs(self, decision: ExecutionDecision) -> None:
        if not decision.legs:
            return
        ids = {item.value: item for item in self.config.instrument_ids}
        for key, target in decision.legs.items():
            instrument_id = ids[key]
            if target == 0:
                if not self.portfolio.is_flat(instrument_id):
                    self.close_all_positions(instrument_id)
                continue
            if target > 0:
                if self.portfolio.is_net_long(instrument_id):
                    continue
                if self.portfolio.is_net_short(instrument_id):
                    self.close_all_positions(instrument_id)
                self._submit_market(instrument_id, OrderSide.BUY)
            else:
                if not self.genome.allow_short:
                    if not self.portfolio.is_flat(instrument_id):
                        self.close_all_positions(instrument_id)
                    continue
                if self.portfolio.is_net_short(instrument_id):
                    continue
                if self.portfolio.is_net_long(instrument_id):
                    self.close_all_positions(instrument_id)
                self._submit_market(instrument_id, OrderSide.SELL)

    def _submit_market(self, instrument_id: InstrumentId, side: OrderSide) -> None:
        instrument = self._instruments[instrument_id.value]
        order = self.order_factory.market(
            instrument_id=instrument_id,
            order_side=side,
            quantity=instrument.make_qty(self.config.trade_size),
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        for instrument_id in self.config.instrument_ids:
            self.close_all_positions(instrument_id)
