from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import Bar, BarType, InstrumentId
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy

from .contracts import MarketBar
from .execution_policy import ExecutionDecision, PositionState, evaluate_execution_policy
from .execution_signals import SignalDirection
from .genome import StrategyGenome
from .nautilus_risk_hook import NautilusRiskMixin
from .risk_runtime import RiskRuntime


class GeneratedBarStrategyConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    family: str
    genome_hash: str


class GeneratedBarStrategy(NautilusRiskMixin, Strategy):
    def __init__(
        self,
        *,
        config: GeneratedBarStrategyConfig,
        genome: StrategyGenome,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config)
        self.genome = genome
        self._bars: list[MarketBar] = []
        self._position_state = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)
        self.instrument = None
        self.last_decision = ExecutionDecision(SignalDirection.FLAT, "not_started")
        self.last_exit_reason: str | None = None
        self._configure_risk_runtime(genome.strategy_id, risk_runtime)

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Could not find instrument for {self.config.instrument_id}")
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)

    def _to_market_bar(self, bar: Bar) -> MarketBar:
        return MarketBar(
            timestamp=datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=timezone.utc),
            venue=self.config.instrument_id.venue.value,
            instrument=self.config.instrument_id.value,
            timeframe=self.genome.timeframe,
            open=bar.open.as_double(),
            high=bar.high.as_double(),
            low=bar.low.as_double(),
            close=bar.close.as_double(),
            volume=bar.volume.as_double(),
        )

    @staticmethod
    def _event_direction(event) -> SignalDirection:
        side = getattr(event, "side", None)
        name = getattr(side, "name", str(side)).upper()
        if name.endswith("LONG"):
            return SignalDirection.LONG
        if name.endswith("SHORT"):
            return SignalDirection.SHORT
        return SignalDirection.FLAT

    def _position_event_matches(self, event) -> bool:
        return getattr(event, "instrument_id", None) == self.config.instrument_id

    def on_position_opened(self, event) -> None:
        if not self._position_event_matches(event):
            return
        direction = self._event_direction(event)
        if direction is SignalDirection.FLAT:
            raise RuntimeError("opened Nautilus position cannot be flat")
        entry_price = float(event.avg_px_open)
        self._position_state = PositionState(
            direction=direction,
            entry_price=entry_price,
            peak_price=entry_price,
            trough_price=entry_price,
            bars_held=0,
        )

    def on_position_changed(self, event) -> None:
        if not self._position_event_matches(event):
            return
        direction = self._event_direction(event)
        if direction is SignalDirection.FLAT:
            self._position_state = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)
            return
        entry_price = float(event.avg_px_open)
        previous = self._position_state
        if previous.direction is direction:
            peak = max(previous.peak_price, entry_price)
            trough = min(previous.trough_price, entry_price)
            bars_held = previous.bars_held
        else:
            peak = entry_price
            trough = entry_price
            bars_held = 0
        self._position_state = PositionState(
            direction=direction,
            entry_price=entry_price,
            peak_price=peak,
            trough_price=trough,
            bars_held=bars_held,
        )

    def on_position_closed(self, event) -> None:
        if self._position_event_matches(event):
            self._position_state = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)

    def _advance_position_state(self, bar: MarketBar) -> None:
        current = self._position_state
        if current.direction is SignalDirection.FLAT:
            return
        self._position_state = PositionState(
            direction=current.direction,
            entry_price=current.entry_price,
            peak_price=max(current.peak_price, float(bar.high)),
            trough_price=min(current.trough_price, float(bar.low)),
            bars_held=current.bars_held + 1,
        )

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self.config.bar_type:
            return
        market_bar = self._to_market_bar(bar)
        self._bars.append(market_bar)
        self._advance_position_state(market_bar)
        decision = evaluate_execution_policy(self.genome, self._bars, self._position_state)
        self.last_decision = decision
        if decision.close_position:
            self.last_exit_reason = decision.reason
        self._apply_decision(decision)

    def _risk_reference_price(self, instrument_id) -> float:
        if not self._bars:
            return 0.0
        return float(self._bars[-1].close)

    def _apply_decision(self, decision: ExecutionDecision) -> None:
        if self.instrument is None:
            return
        instrument_id = self.config.instrument_id

        if decision.close_position and not self.portfolio.is_flat(instrument_id):
            self.close_all_positions(instrument_id)

        if decision.direction is SignalDirection.FLAT:
            return
        if decision.direction is SignalDirection.LONG:
            if self.portfolio.is_net_long(instrument_id):
                return
            if self.portfolio.is_net_short(instrument_id):
                self.close_all_positions(instrument_id)
            self._submit_market(OrderSide.BUY)
            return
        if not self.genome.allow_short:
            if self.portfolio.is_net_long(instrument_id):
                self.close_all_positions(instrument_id)
            return
        if self.portfolio.is_net_short(instrument_id):
            return
        if self.portfolio.is_net_long(instrument_id):
            self.close_all_positions(instrument_id)
        self._submit_market(OrderSide.SELL)

    def _submit_market(self, side: OrderSide) -> None:
        if self.instrument is None:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(self.config.trade_size),
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)
