from __future__ import annotations

from typing import Protocol

from mastertrd.contracts import MarketBar

from .binance_public import parse_kline_row
from .archive import validate_bar_sequence


class OhlcvSource(Protocol):
    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None): ...


def fetch_ohlcv_fallback(
    exchange: OhlcvSource,
    *,
    venue: str,
    symbol: str,
    instrument: str,
    timeframe: str,
    since: int | None = None,
    limit: int | None = None,
) -> tuple[MarketBar, ...]:
    if not venue or not symbol or not instrument or not timeframe:
        raise ValueError("venue, symbol, instrument and timeframe are required")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")

    rows = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    bars = [
        parse_kline_row(
            row,
            symbol=instrument,
            interval=timeframe,
            venue=venue,
        )
        for row in rows
    ]
    return validate_bar_sequence(bars)
