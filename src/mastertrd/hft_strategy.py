from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import Mapping

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import InstrumentId
from nautilus_trader.trading.strategy import Strategy

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
    # Positive inventory shifts both quotes downward to favor inventory reduction;
    # negative inventory shifts them upward. The bounded linear skew keeps the
    # strategy deterministic while the separate risk runtime caps actual size.
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
    """Authoritative Nautilus shell for HFT-family execution.

    Tick/L2 subscriptions, state transitions and order application are added
    behind integration behavior tests. The pure market-state and intent policy
    above is shared by backtest, PAPER and live Nautilus adapters.
    """

    def __init__(
        self,
        *,
        config: GeneratedHftStrategyConfig,
        genome: StrategyGenome,
        risk_runtime: RiskRuntime | None = None,
    ) -> None:
        super().__init__(config)
        self.genome = genome
        self._configure_risk_runtime(genome.strategy_id, risk_runtime)
