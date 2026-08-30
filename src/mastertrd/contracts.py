from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from math import isfinite
from typing import Any, Mapping


class RuntimeMode(StrEnum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    DEMO = "DEMO"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class StrategyState(StrEnum):
    IDEA = "IDEA"
    SCREENED = "SCREENED"
    BACKTESTED = "BACKTESTED"
    ROBUST = "ROBUST"
    HIDDEN_PASS = "HIDDEN_PASS"
    PAPER = "PAPER"
    CHALLENGER = "CHALLENGER"
    CHAMPION = "CHAMPION"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class MarketBar:
    timestamp: datetime
    venue: str
    instrument: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    extras: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if not self.venue or not self.instrument or not self.timeframe:
            raise ValueError("venue, instrument and timeframe are required")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(float(v)) for v in values):
            raise ValueError("market values must be finite")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is inconsistent with OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is inconsistent with OHLC")


@dataclass(frozen=True, slots=True)
class MarketTick:
    timestamp: datetime
    venue: str
    instrument: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last: float | None = None
    last_size: float = 0.0
    extras: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        if not self.venue or not self.instrument:
            raise ValueError("venue and instrument are required")
        numeric = (self.bid, self.ask, self.bid_size, self.ask_size, self.last_size)
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("tick values must be finite")
        if self.bid <= 0 or self.ask <= 0:
            raise ValueError("bid and ask must be positive")
        if self.bid_size < 0 or self.ask_size < 0 or self.last_size < 0:
            raise ValueError("tick sizes cannot be negative")
        if self.ask < self.bid:
            raise ValueError("crossed tick book is invalid")
        if self.last is not None:
            if not isfinite(float(self.last)) or self.last <= 0:
                raise ValueError("last price must be positive and finite")


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    strategy_id: str
    genome_hash: str
    dataset_hash: str
    code_hash: str
    engine: str
    engine_version: str
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    profit_factor: float
    expectancy: float
    trade_count: int
    turnover: float
    fees: float
    slippage: float
    scores: Mapping[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not all((self.strategy_id, self.genome_hash, self.dataset_hash, self.code_hash, self.engine)):
            raise ValueError("identity fields are required")
        numeric = (
            self.total_return, self.sharpe, self.sortino, self.max_drawdown,
            self.profit_factor, self.expectancy, self.turnover, self.fees, self.slippage,
            *self.scores.values(),
        )
        if not all(isfinite(float(v)) for v in numeric):
            raise ValueError("result metrics must be finite")
        if self.trade_count < 0 or self.fees < 0 or self.slippage < 0:
            raise ValueError("counts/costs cannot be negative")
