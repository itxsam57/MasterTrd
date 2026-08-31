from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import TypeAlias

from .contracts import MarketBar, MarketTick


MarketPayload: TypeAlias = MarketBar | MarketTick


@dataclass(frozen=True, slots=True)
class MarketStreamEvent:
    event_id: str
    data: MarketPayload
    timestamp_ns: int

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns cannot be negative")

    @property
    def kind(self) -> str:
        return "bar" if isinstance(self.data, MarketBar) else "tick"

    @property
    def bar(self) -> MarketBar:
        if not isinstance(self.data, MarketBar):
            raise TypeError("market stream event does not contain a bar")
        return self.data

    @property
    def tick(self) -> MarketTick:
        if not isinstance(self.data, MarketTick):
            raise TypeError("market stream event does not contain a tick")
        return self.data


RawMarketPayload: TypeAlias = Mapping[str, object] | MarketStreamEvent


class MarketStream:
    def __init__(self, source: Iterable[RawMarketPayload]):
        self._source = source

    @staticmethod
    def _required_text(raw: Mapping[str, object], field: str) -> str:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is required")
        return value.strip()

    @staticmethod
    def _required_float(raw: Mapping[str, object], field: str) -> float:
        try:
            value = float(raw[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be numeric") from exc
        if not isfinite(value):
            raise ValueError(f"{field} must be finite")
        return value

    @staticmethod
    def _timestamp(raw: Mapping[str, object]) -> tuple[datetime, int]:
        try:
            milliseconds = float(raw["timestamp_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("timestamp_ms must be numeric") from exc
        if not isfinite(milliseconds) or milliseconds < 0:
            raise ValueError("timestamp_ms must be finite and non-negative")
        timestamp_ns = int(milliseconds * 1_000_000)
        timestamp = datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
        return timestamp, timestamp_ns

    @classmethod
    def normalize_bar(cls, raw: Mapping[str, object]) -> MarketStreamEvent:
        event_id = cls._required_text(raw, "event_id")
        timestamp, timestamp_ns = cls._timestamp(raw)
        bar = MarketBar(
            timestamp=timestamp,
            venue=cls._required_text(raw, "venue"),
            instrument=cls._required_text(raw, "instrument"),
            timeframe=cls._required_text(raw, "timeframe"),
            open=cls._required_float(raw, "open"),
            high=cls._required_float(raw, "high"),
            low=cls._required_float(raw, "low"),
            close=cls._required_float(raw, "close"),
            volume=cls._required_float(raw, "volume"),
            extras={
                key: value
                for key, value in raw.items()
                if key
                not in {
                    "event_id",
                    "venue",
                    "instrument",
                    "timeframe",
                    "timestamp_ms",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                }
            },
        )
        return MarketStreamEvent(event_id=event_id, data=bar, timestamp_ns=timestamp_ns)

    @classmethod
    def normalize_tick(cls, raw: Mapping[str, object]) -> MarketStreamEvent:
        event_id = cls._required_text(raw, "event_id")
        timestamp, timestamp_ns = cls._timestamp(raw)
        last_raw = raw.get("last")
        last_size_raw = raw.get("last_size", 0.0)
        tick = MarketTick(
            timestamp=timestamp,
            venue=cls._required_text(raw, "venue"),
            instrument=cls._required_text(raw, "instrument"),
            bid=cls._required_float(raw, "bid"),
            ask=cls._required_float(raw, "ask"),
            bid_size=cls._required_float(raw, "bid_size"),
            ask_size=cls._required_float(raw, "ask_size"),
            last=None if last_raw is None else cls._required_float(raw, "last"),
            last_size=0.0 if last_size_raw is None else cls._required_float(raw, "last_size"),
            extras={
                key: value
                for key, value in raw.items()
                if key
                not in {
                    "event_id",
                    "venue",
                    "instrument",
                    "timestamp_ms",
                    "bid",
                    "ask",
                    "bid_size",
                    "ask_size",
                    "last",
                    "last_size",
                }
            },
        )
        return MarketStreamEvent(event_id=event_id, data=tick, timestamp_ns=timestamp_ns)

    @classmethod
    def normalize(cls, raw: RawMarketPayload) -> MarketStreamEvent:
        if isinstance(raw, MarketStreamEvent):
            return raw
        if not isinstance(raw, Mapping):
            raise TypeError("market stream source values must be mappings or MarketStreamEvent values")
        if "timeframe" in raw or {"open", "high", "low", "close", "volume"}.issubset(raw):
            return cls.normalize_bar(raw)
        if {"bid", "ask", "bid_size", "ask_size"}.issubset(raw):
            return cls.normalize_tick(raw)
        raise ValueError("unsupported market event payload")

    def __iter__(self) -> Iterator[MarketStreamEvent]:
        for raw in self._source:
            yield self.normalize(raw)

    def reconnect(self, source: Iterable[RawMarketPayload]) -> "MarketStream":
        return MarketStream(source)
