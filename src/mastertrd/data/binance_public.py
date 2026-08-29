from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from mastertrd.contracts import MarketBar


_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_PERIOD = re.compile(r"^\d{4}-\d{2}$")
_MARKET_PATHS = {
    "spot": "spot",
    "um": "futures/um",
    "cm": "futures/cm",
}


def binance_kline_url(*, market: str, symbol: str, interval: str, period: str) -> str:
    market_key = market.lower()
    if market_key not in _MARKET_PATHS:
        raise ValueError("market must be one of: spot, um, cm")
    if not _TOKEN.fullmatch(symbol) or not _TOKEN.fullmatch(interval):
        raise ValueError("symbol and interval must contain only safe token characters")
    if not _PERIOD.fullmatch(period):
        raise ValueError("period must use YYYY-MM format")
    symbol = symbol.upper()
    filename = f"{symbol}-{interval}-{period}.zip"
    return (
        "https://data.binance.vision/data/"
        f"{_MARKET_PATHS[market_key]}/monthly/klines/{symbol}/{interval}/{filename}"
    )


def _timestamp_from_epoch(raw: str | int) -> datetime:
    value = int(raw)
    # Binance public archives historically used milliseconds and newer datasets
    # may use microseconds. Use magnitude rather than a date cutoff so mixed
    # historical archives remain parseable and deterministic.
    divisor = 1_000_000 if abs(value) >= 100_000_000_000_000 else 1_000
    return datetime.fromtimestamp(value / divisor, tz=timezone.utc)


def parse_kline_row(
    row: Sequence[str | int | float],
    *,
    symbol: str,
    interval: str,
    venue: str = "BINANCE",
) -> MarketBar:
    if len(row) < 6:
        raise ValueError("Binance kline row requires at least 6 fields")
    return MarketBar(
        timestamp=_timestamp_from_epoch(row[0]),
        venue=venue,
        instrument=symbol.upper(),
        timeframe=interval,
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )
