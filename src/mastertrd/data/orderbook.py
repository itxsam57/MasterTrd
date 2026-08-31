from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from math import isfinite


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    price: float
    size: float

    def __post_init__(self) -> None:
        if not isfinite(float(self.price)) or self.price <= 0:
            raise ValueError("order-book price must be positive and finite")
        if not isfinite(float(self.size)) or self.size <= 0:
            raise ValueError("order-book size must be positive and finite")


@dataclass(frozen=True, slots=True)
class OrderBookTrade:
    side: str
    price: float
    size: float

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("trade side must be BUY or SELL")
        if not isfinite(float(self.price)) or self.price <= 0:
            raise ValueError("trade price must be positive and finite")
        if not isfinite(float(self.size)) or self.size <= 0:
            raise ValueError("trade size must be positive and finite")


@dataclass(frozen=True, slots=True)
class OrderBookEvent:
    sequence: int
    exchange_timestamp_ns: int
    local_timestamp_ns: int
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    trades: tuple[OrderBookTrade, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if self.exchange_timestamp_ns < 0 or self.local_timestamp_ns < 0:
            raise ValueError("order-book timestamps must be non-negative")
        if self.local_timestamp_ns < self.exchange_timestamp_ns:
            raise ValueError("local timestamp cannot precede exchange timestamp")
        if not self.bids or not self.asks:
            raise ValueError("order-book event requires two-sided depth")
        best_bid = max(level.price for level in self.bids)
        best_ask = min(level.price for level in self.asks)
        if best_bid > best_ask:
            raise ValueError("crossed order book is invalid")


@dataclass(frozen=True, slots=True)
class OrderBookDataset:
    venue: str
    instrument: str
    source_id: str
    events: tuple[OrderBookEvent, ...]
    synthetic: bool = False

    def __post_init__(self) -> None:
        if not self.venue or not self.instrument or not self.source_id:
            raise ValueError("venue, instrument and source_id are required")
        if not self.events:
            raise ValueError("order-book dataset cannot be empty")

        previous = self.events[0]
        for current in self.events[1:]:
            if current.sequence != previous.sequence + 1:
                raise ValueError("order-book sequence must be contiguous")
            if current.exchange_timestamp_ns <= previous.exchange_timestamp_ns:
                raise ValueError("exchange timestamp must increase monotonically")
            if current.local_timestamp_ns <= previous.local_timestamp_ns:
                raise ValueError("local timestamp must increase monotonically")
            previous = current

    @property
    def dataset_hash(self) -> str:
        payload = asdict(self)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
