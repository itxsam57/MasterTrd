from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Sequence, Any

from .contracts import MarketBar


_TIMEFRAME = re.compile(r"^(?P<step>[1-9]\d*)(?P<unit>[mhdwM])$")
_AGGREGATION = {
    "m": "MINUTE",
    "h": "HOUR",
    "d": "DAY",
    "w": "WEEK",
    "M": "MONTH",
}


def _bar_type_string(instrument: Any, timeframe: str) -> str:
    match = _TIMEFRAME.fullmatch(timeframe)
    if match is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    step = int(match.group("step"))
    aggregation = _AGGREGATION[match.group("unit")]
    return f"{instrument.id}-{step}-{aggregation}-LAST-EXTERNAL"


def _unix_nanos(timestamp: datetime) -> int:
    if timestamp.tzinfo is None:
        raise ValueError("market bar timestamp must be timezone-aware")
    utc = timestamp.astimezone(timezone.utc)
    seconds = int(utc.timestamp())
    return seconds * 1_000_000_000 + utc.microsecond * 1_000


def _validate_identity(bars: Sequence[MarketBar], instrument: Any) -> str:
    timeframe = bars[0].timeframe
    instrument_symbol = str(instrument.raw_symbol).upper()
    instrument_venue = str(instrument.id.venue).upper()

    for bar in bars:
        if bar.instrument.upper() != instrument_symbol:
            raise ValueError(
                f"market bar instrument {bar.instrument} does not match {instrument_symbol}"
            )
        if bar.venue.upper() != instrument_venue:
            raise ValueError(f"market bar venue {bar.venue} does not match {instrument_venue}")
        if bar.timeframe != timeframe:
            raise ValueError("market bars must use one timeframe")
    return timeframe


def market_bars_to_nautilus(
    market_bars: Iterable[MarketBar],
    *,
    instrument: Any,
) -> tuple[Any, ...]:
    """Convert canonical MarketBar values into real NautilusTrader Bar objects.

    The bridge validates symbol, venue, and timeframe before constructing data and
    uses the supplied instrument's factory methods so price/size precision matches
    the market definition used by the Nautilus backtest engine.
    """
    bars = tuple(market_bars)
    if not bars:
        return ()

    timeframe = _validate_identity(bars, instrument)

    from nautilus_trader.model.data import Bar, BarType

    bar_type = BarType.from_str(_bar_type_string(instrument, timeframe))
    converted = []
    previous_ts: int | None = None
    for market_bar in bars:
        ts = _unix_nanos(market_bar.timestamp)
        if previous_ts is not None and ts <= previous_ts:
            raise ValueError("market bars must be strictly increasing by timestamp")
        previous_ts = ts
        converted.append(
            Bar(
                bar_type,
                instrument.make_price(market_bar.open),
                instrument.make_price(market_bar.high),
                instrument.make_price(market_bar.low),
                instrument.make_price(market_bar.close),
                instrument.make_qty(market_bar.volume),
                ts,
                ts,
            )
        )
    return tuple(converted)
