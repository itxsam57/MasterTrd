from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import Bar, BarType, InstrumentId
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.trading.strategy import Strategy

from .contracts import MarketBar
from .execution_signals import SignalDecision, SignalDirection, evaluate_bar_signal
from .genome import StrategyGenome


class GeneratedBarStrategyConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    family: str
    genome_hash: str


class GeneratedBarStrategy(Strategy):
    def __init__(self, *, config: GeneratedBarStrategyConfig, genome: StrategyGenome) -> None:
        super().__init__(config)
        self.genome = genome
        self._bars: list[MarketBar] = []
        self.instrument = None
        self.last_decision = SignalDecision(SignalDirection.FLAT, "not_started")

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

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self.config.bar_type:
            return
        self._bars.append(self._to_market_bar(bar))
        decision = evaluate_bar_signal(self.genome, self._bars)
        self.last_decision = decision
        self._apply_decision(decision)

    def _apply_decision(self, decision: SignalDecision) -> None:
        if self.instrument is None or decision.direction is SignalDirection.FLAT:
            return
        instrument_id = self.config.instrument_id
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
