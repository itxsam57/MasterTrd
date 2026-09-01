from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import Mapping

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.model.enums import BookType, OrderSide
from nautilus_trader.trading.strategy import Strategy

from .execution_policy import HftPositionState, evaluate_hft_execution_policy
from .execution_signals import SignalDirection
from .genome import StrategyGenome
from .nautilus_risk_hook import NautilusRiskMixin
from .risk_runtime import RiskRuntime


@dataclass(frozen=True, slots=True)
class HftBookState:
    instrument_id: str
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    tick_size: float
    mid_history: tuple[float, ...] = ()
    inventory: float = 0.0
    bid_levels: tuple[tuple[float, float], ...] = ()
    ask_levels: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        for name in ("bid_price", "ask_price", "bid_size", "ask_size", "tick_size"):
            value = float(getattr(self, name))
            if not isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be positive and finite")
        if self.bid_price > self.ask_price:
            raise ValueError("HFT book cannot be crossed")
        if not isfinite(float(self.inventory)):
            raise ValueError("inventory must be finite")
        if any(not isfinite(float(value)) or float(value) <= 0.0 for value in self.mid_history):
            raise ValueError("mid_history must contain positive finite prices")
        self._validate_levels(self.bid_levels, "bid_levels")
        self._validate_levels(self.ask_levels, "ask_levels")

    @staticmethod
    def _validate_levels(levels: tuple[tuple[float, float], ...], name: str) -> None:
        for price, size in levels:
            if not isfinite(float(price)) or float(price) <= 0.0:
                raise ValueError(f"{name} prices must be positive and finite")
            if not isfinite(float(size)) or float(size) <= 0.0:
                raise ValueError(f"{name} sizes must be positive and finite")

    @property
    def midpoint(self) -> float:
        return (float(self.bid_price) + float(self.ask_price)) / 2.0

    @property
    def spread_ticks(self) -> float:
        return (float(self.ask_price) - float(self.bid_price)) / float(self.tick_size)

    @property
    def spread_bps(self) -> float:
        return (float(self.ask_price) - float(self.bid_price)) / self.midpoint * 10_000.0

    def imbalance(self, levels: int) -> float:
        if levels <= 0:
            raise ValueError("order-book levels must be positive")
        bid_sizes = [float(size) for _, size in self.bid_levels[:levels]] or [float(self.bid_size)]
        ask_sizes = [float(size) for _, size in self.ask_levels[:levels]] or [float(self.ask_size)]
        bid_total = sum(bid_sizes)
        ask_total = sum(ask_sizes)
        total = bid_total + ask_total
        return 0.0 if total <= 0.0 else (bid_total - ask_total) / total


@dataclass(frozen=True, slots=True)
class HftOrderIntent:
    instrument_id: str
    direction: SignalDirection
    reason: str
    price: float | None = None
    post_only: bool = False
    quantity_weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.instrument_id or not self.reason:
            raise ValueError("HFT order intent identity and reason are required")
        if self.direction is SignalDirection.FLAT:
            raise ValueError("HFT order intent cannot be flat")
        if self.price is not None and (not isfinite(float(self.price)) or float(self.price) <= 0.0):
            raise ValueError("HFT limit price must be positive and finite")
        if self.post_only and self.price is None:
            raise ValueError("post-only HFT intent requires a limit price")
        if not isfinite(float(self.quantity_weight)) or float(self.quantity_weight) <= 0.0:
            raise ValueError("quantity_weight must be positive and finite")


@dataclass(slots=True)
class _OpenHftPosition:
    direction: SignalDirection
    entry_price: float
    signed_qty: float
    ticks_held: int = 0


def _exact_states(
    genome: StrategyGenome,
    states: Mapping[str, HftBookState],
) -> tuple[HftBookState, ...]:
    if set(states) != set(genome.instruments):
        raise ValueError("HFT market state must match the candidate instrument set exactly")
    ordered = tuple(states[key] for key in genome.instruments)
    for expected, state in zip(genome.instruments, ordered, strict=True):
        if state.instrument_id != expected:
            raise ValueError("HFT market state instrument identity mismatch")
    return ordered


def _positive_number(mapping: Mapping[str, object], key: str) -> float:
    try:
        value = float(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be positive and finite") from exc
    if not isfinite(value) or value <= 0.0:
        raise ValueError(f"{key} must be positive and finite")
    return value


def _positive_int(mapping: Mapping[str, object], key: str) -> int:
    value = _positive_number(mapping, key)
    integer = int(value)
    if float(integer) != value:
        raise ValueError(f"{key} must be a positive integer")
    return integer


def _market_intent(instrument_id: str, direction: SignalDirection, reason: str) -> HftOrderIntent:
    return HftOrderIntent(
        instrument_id=instrument_id,
        direction=direction,
        reason=reason,
    )


def _limit_intent(
    instrument_id: str,
    direction: SignalDirection,
    price: float,
    reason: str,
) -> HftOrderIntent:
    return HftOrderIntent(
        instrument_id=instrument_id,
        direction=direction,
        price=price,
        post_only=True,
        reason=reason,
    )


def _scalping_intents(genome: StrategyGenome, state: HftBookState) -> tuple[HftOrderIntent, ...]:
    if str(genome.entry.get("type", genome.entry.get("kind"))) != "micro_momentum":
        raise ValueError("scalping entry requires micro_momentum")
    ticks = _positive_int(genome.entry, "ticks")
    spread_limit = _positive_number(genome.filters, "spread_max_ticks")
    if state.spread_ticks > spread_limit:
        return ()
    if len(state.mid_history) < ticks + 1:
        return ()
    current = float(state.mid_history[-1])
    reference = float(state.mid_history[-ticks - 1])
    if current > reference:
        return (_market_intent(state.instrument_id, SignalDirection.LONG, "micro_momentum"),)
    if current < reference and genome.allow_short:
        return (_market_intent(state.instrument_id, SignalDirection.SHORT, "micro_momentum"),)
    return ()


def _grid_intents(genome: StrategyGenome, state: HftBookState) -> tuple[HftOrderIntent, ...]:
    if str(genome.entry.get("type", genome.entry.get("kind"))) != "dynamic_grid":
        raise ValueError("grid entry requires dynamic_grid")
    levels = _positive_int(genome.entry, "levels")
    spacing_bps = _positive_number(genome.entry, "spacing_bps")
    midpoint = state.midpoint
    intents: list[HftOrderIntent] = []
    for level in range(1, levels + 1):
        offset = spacing_bps * level / 10_000.0
        buy_price = midpoint * (1.0 - offset)
        sell_price = midpoint * (1.0 + offset)
        if buy_price <= 0.0:
            raise ValueError("grid spacing produces a non-positive bid")
        intents.append(_limit_intent(state.instrument_id, SignalDirection.LONG, buy_price, "dynamic_grid"))
        intents.append(_limit_intent(state.instrument_id, SignalDirection.SHORT, sell_price, "dynamic_grid"))
    return tuple(intents)


def _market_making_intents(
    genome: StrategyGenome,
    state: HftBookState,
) -> tuple[HftOrderIntent, ...]:
    if str(genome.entry.get("type", genome.entry.get("kind"))) != "inventory_skew_mm":
        raise ValueError("market_making entry requires inventory_skew_mm")
    half_spread_bps = _positive_number(genome.entry, "half_spread_bps")
    inventory_skew_bps = float(state.inventory) * half_spread_bps
    center = state.midpoint * (1.0 - inventory_skew_bps / 10_000.0)
    half_spread = half_spread_bps / 10_000.0
    bid = center * (1.0 - half_spread)
    ask = center * (1.0 + half_spread)
    if bid <= 0.0 or ask <= bid:
        raise ValueError("market-making quote calculation produced invalid prices")
    return (
        _limit_intent(state.instrument_id, SignalDirection.LONG, bid, "inventory_skew_mm"),
        _limit_intent(state.instrument_id, SignalDirection.SHORT, ask, "inventory_skew_mm"),
    )


def _order_book_intents(genome: StrategyGenome, state: HftBookState) -> tuple[HftOrderIntent, ...]:
    if str(genome.entry.get("type", genome.entry.get("kind"))) != "order_book_imbalance":
        raise ValueError("order_book entry requires order_book_imbalance")
    levels = _positive_int(genome.entry, "levels")
    threshold = _positive_number(genome.entry, "threshold")
    if threshold > 1.0:
        raise ValueError("order-book imbalance threshold cannot exceed one")
    imbalance = state.imbalance(levels)
    if imbalance >= threshold:
        return (_market_intent(state.instrument_id, SignalDirection.LONG, "order_book_imbalance"),)
    if imbalance <= -threshold and genome.allow_short:
        return (_market_intent(state.instrument_id, SignalDirection.SHORT, "order_book_imbalance"),)
    return ()


def _cross_venue_intents(
    genome: StrategyGenome,
    states: tuple[HftBookState, ...],
) -> tuple[HftOrderIntent, ...]:
    if str(genome.entry.get("type", genome.entry.get("kind"))) != "cross_venue_spread":
        raise ValueError("cross_venue_arb entry requires cross_venue_spread")
    if len(states) != 2:
        raise ValueError("cross_venue_arb requires exactly two market states")
    min_edge_bps = _positive_number(genome.entry, "min_edge_bps")
    left, right = states
    if left.midpoint <= right.midpoint:
        cheap, rich = left, right
    else:
        cheap, rich = right, left
    edge_bps = (rich.midpoint - cheap.midpoint) / cheap.midpoint * 10_000.0
    if edge_bps < min_edge_bps:
        return ()
    if not genome.allow_short:
        raise ValueError("cross_venue_arb requires short-capable execution")
    return (
        _market_intent(cheap.instrument_id, SignalDirection.LONG, "cross_venue_spread"),
        _market_intent(rich.instrument_id, SignalDirection.SHORT, "cross_venue_spread"),
    )


def evaluate_hft_entry_intents(
    genome: StrategyGenome,
    states: Mapping[str, HftBookState],
) -> tuple[HftOrderIntent, ...]:
    ordered = _exact_states(genome, states)
    if genome.family == "scalping":
        if len(ordered) != 1:
            raise ValueError("scalping requires exactly one instrument")
        return _scalping_intents(genome, ordered[0])
    if genome.family == "grid":
        if len(ordered) != 1:
            raise ValueError("grid requires exactly one instrument")
        return _grid_intents(genome, ordered[0])
    if genome.family == "market_making":
        if len(ordered) != 1:
            raise ValueError("market_making requires exactly one instrument")
        return _market_making_intents(genome, ordered[0])
    if genome.family == "order_book":
        if len(ordered) != 1:
            raise ValueError("order_book requires exactly one instrument")
        return _order_book_intents(genome, ordered[0])
    if genome.family == "cross_venue_arb":
        return _cross_venue_intents(genome, ordered)
    raise ValueError(f"unsupported HFT execution family: {genome.family}")


class GeneratedHftStrategyConfig(StrategyConfig):
    instrument_ids: tuple[InstrumentId, ...]
    trade_size: Decimal
    family: str
    genome_hash: str
    data_level: str


class GeneratedHftStrategy(NautilusRiskMixin, Strategy):
    """Authoritative Nautilus execution strategy for all admitted HFT families."""

    def __init__(
        self,
        *,
        config: GeneratedHftStrategyConfig,
        genome: StrategyGenome,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config)
        self.genome = genome
        self.instruments: dict[str, object] = {}
        self._states: dict[str, HftBookState] = {}
        self._mid_history: dict[str, list[float]] = {
            instrument_id: [] for instrument_id in genome.instruments
        }
        self._positions: dict[str, _OpenHftPosition] = {}
        self.last_intents: tuple[HftOrderIntent, ...] = ()
        self.last_exit_reason: str | None = None
        self._configure_risk_runtime(genome.strategy_id, risk_runtime)

    def on_start(self) -> None:
        for instrument_id in self.config.instrument_ids:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(f"Could not find instrument for {instrument_id}")
                self.stop()
                return
            self.instruments[instrument_id.value] = instrument

        data_level = str(self.config.data_level)
        if data_level == "L2":
            for instrument_id in self.config.instrument_ids:
                self.subscribe_order_book_deltas(instrument_id, BookType.L2_MBP)
            return
        if data_level == "TICK":
            for instrument_id in self.config.instrument_ids:
                self.subscribe_quote_ticks(instrument_id)
            return
        raise RuntimeError(f"unsupported HFT Nautilus data level: {data_level}")

    @staticmethod
    def _event_direction(event) -> SignalDirection:
        side = getattr(event, "side", None)
        name = getattr(side, "name", str(side)).upper()
        if name.endswith("LONG"):
            return SignalDirection.LONG
        if name.endswith("SHORT"):
            return SignalDirection.SHORT
        return SignalDirection.FLAT

    def _record_position_event(self, event) -> None:
        instrument_id = getattr(getattr(event, "instrument_id", None), "value", None)
        if instrument_id not in self._mid_history:
            return
        direction = self._event_direction(event)
        if direction is SignalDirection.FLAT:
            self._positions.pop(instrument_id, None)
            return
        entry_price = float(event.avg_px_open)
        signed_qty = float(event.signed_qty)
        previous = self._positions.get(instrument_id)
        ticks_held = previous.ticks_held if previous and previous.direction is direction else 0
        self._positions[instrument_id] = _OpenHftPosition(
            direction=direction,
            entry_price=entry_price,
            signed_qty=signed_qty,
            ticks_held=ticks_held,
        )

    def on_position_opened(self, event) -> None:
        self._record_position_event(event)

    def on_position_changed(self, event) -> None:
        self._record_position_event(event)

    def on_position_closed(self, event) -> None:
        instrument_id = getattr(getattr(event, "instrument_id", None), "value", None)
        if instrument_id in self._mid_history:
            self._positions.pop(instrument_id, None)

    def _instrument_tick_size(self, instrument_id: str) -> float:
        instrument = self.instruments[instrument_id]
        increment = getattr(instrument, "price_increment", None)
        if increment is None:
            raise RuntimeError(f"instrument {instrument_id} has no price increment")
        if hasattr(increment, "as_double"):
            return float(increment.as_double())
        return float(increment)

    def _remember_state(
        self,
        instrument_id: str,
        *,
        bid_price: float,
        ask_price: float,
        bid_size: float,
        ask_size: float,
    ) -> HftBookState:
        midpoint = (float(bid_price) + float(ask_price)) / 2.0
        history = self._mid_history[instrument_id]
        history.append(midpoint)
        if len(history) > 4096:
            del history[:-4096]
        position = self._positions.get(instrument_id)
        state = HftBookState(
            instrument_id=instrument_id,
            bid_price=float(bid_price),
            ask_price=float(ask_price),
            bid_size=float(bid_size),
            ask_size=float(ask_size),
            tick_size=self._instrument_tick_size(instrument_id),
            mid_history=tuple(history),
            inventory=0.0 if position is None else position.signed_qty,
        )
        self._states[instrument_id] = state
        return state

    @staticmethod
    def _numeric(value) -> float:
        if hasattr(value, "as_double"):
            return float(value.as_double())
        return float(value)

    def on_quote_tick(self, tick) -> None:
        instrument_id = tick.instrument_id.value
        if instrument_id not in self.instruments:
            return
        self._remember_state(
            instrument_id,
            bid_price=self._numeric(tick.bid_price),
            ask_price=self._numeric(tick.ask_price),
            bid_size=self._numeric(tick.bid_size),
            ask_size=self._numeric(tick.ask_size),
        )
        self._process_market_state()

    def on_order_book_deltas(self, deltas) -> None:
        instrument_id = deltas.instrument_id.value
        if instrument_id not in self.instruments:
            return
        book = self.cache.order_book(deltas.instrument_id)
        if book is None:
            return
        bid_price = book.best_bid_price()
        ask_price = book.best_ask_price()
        bid_size = book.best_bid_size()
        ask_size = book.best_ask_size()
        if bid_price is None or ask_price is None or bid_size is None or ask_size is None:
            return
        self._remember_state(
            instrument_id,
            bid_price=self._numeric(bid_price),
            ask_price=self._numeric(ask_price),
            bid_size=self._numeric(bid_size),
            ask_size=self._numeric(ask_size),
        )
        self._process_market_state()

    def _cross_venue_spread_bps(self) -> float:
        if len(self.genome.instruments) != 2 or any(
            instrument_id not in self._states for instrument_id in self.genome.instruments
        ):
            return float("inf")
        left = self._states[self.genome.instruments[0]].midpoint
        right = self._states[self.genome.instruments[1]].midpoint
        cheap = min(left, right)
        rich = max(left, right)
        return (rich - cheap) / cheap * 10_000.0

    def _evaluate_open_position_exit(self, instrument_id: str) -> bool:
        position = self._positions.get(instrument_id)
        state = self._states.get(instrument_id)
        if position is None or state is None:
            return False
        position.ticks_held += 1
        spread_bps = (
            self._cross_venue_spread_bps()
            if self.genome.family == "cross_venue_arb"
            else state.spread_bps
        )
        decision = evaluate_hft_execution_policy(
            self.genome,
            HftPositionState(
                direction=position.direction,
                entry_price=position.entry_price,
                current_price=state.midpoint,
                tick_size=state.tick_size,
                ticks_held=position.ticks_held,
                inventory=position.signed_qty,
                imbalance=state.imbalance(int(self.genome.entry.get("levels", 1))),
                spread_bps=spread_bps,
            ),
        )
        if not decision.close_position:
            return False
        self.last_exit_reason = decision.reason
        self.cancel_all_orders(self.instruments[instrument_id].id)
        self.close_all_positions(self.instruments[instrument_id].id)
        return True

    def _process_market_state(self) -> None:
        if any(instrument_id not in self._states for instrument_id in self.genome.instruments):
            return

        exited = False
        for instrument_id in self.genome.instruments:
            exited = self._evaluate_open_position_exit(instrument_id) or exited
        if exited:
            return

        has_open_position = any(
            instrument_id in self._positions for instrument_id in self.genome.instruments
        )
        if has_open_position and self.genome.family not in {"grid", "market_making"}:
            return

        if self.genome.family in {"grid", "market_making"}:
            for instrument_id in self.genome.instruments:
                self.cancel_all_orders(self.instruments[instrument_id].id)

        intents = evaluate_hft_entry_intents(self.genome, self._states)
        self.last_intents = intents
        for intent in intents:
            self._submit_intent(intent)

    def _submit_intent(self, intent: HftOrderIntent) -> None:
        instrument = self.instruments[intent.instrument_id]
        side = OrderSide.BUY if intent.direction is SignalDirection.LONG else OrderSide.SELL
        quantity = instrument.make_qty(
            self.config.trade_size * Decimal(str(intent.quantity_weight)),
        )
        if intent.price is None:
            order = self.order_factory.market(
                instrument_id=instrument.id,
                order_side=side,
                quantity=quantity,
            )
        else:
            order = self.order_factory.limit(
                instrument_id=instrument.id,
                order_side=side,
                quantity=quantity,
                price=instrument.make_price(intent.price),
                post_only=intent.post_only,
            )
        self.submit_order(order)

    def _risk_reference_price(self, instrument_id) -> float:
        state = self._states.get(instrument_id.value)
        return 0.0 if state is None else state.midpoint

    def on_stop(self) -> None:
        for instrument_id in self.config.instrument_ids:
            self.cancel_all_orders(instrument_id)
            self.close_all_positions(instrument_id)
