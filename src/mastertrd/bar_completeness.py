from __future__ import annotations

import json
from math import isfinite
import time
from urllib.parse import urlencode
from urllib.request import urlopen


_SUPPORTED_FIXED_TIMEFRAMES_MS: dict[str, int] = {
    "1s": 1_000,
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


def timeframe_milliseconds(timeframe: str) -> int:
    value = str(timeframe).strip()
    try:
        return _SUPPORTED_FIXED_TIMEFRAMES_MS[value]
    except KeyError as exc:
        raise ValueError(f"unsupported fixed Binance timeframe: {timeframe}") from exc


def expected_closed_start_ms(*, observed_ms: int, timeframe: str) -> int:
    width = timeframe_milliseconds(timeframe)
    observed = int(observed_ms)
    if observed < width:
        raise ValueError("observed_ms is too early for a closed candle")
    return ((observed // width) * width) - width


def canonical_binance_kline_event_id(symbol: str, timeframe: str, start_ms: int) -> str:
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("Binance symbol is required")
    normalized_timeframe = str(timeframe).strip()
    timeframe_milliseconds(normalized_timeframe)
    start = int(start_ms)
    if start < 0:
        raise ValueError("kline start_ms cannot be negative")
    return f"binance-kline:{normalized_symbol}:{normalized_timeframe}:{start}"


def _finite_number(value: object, *, field: str, positive: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Binance recovered {field} is invalid") from exc
    if not isfinite(number):
        raise RuntimeError(f"Binance recovered {field} must be finite")
    if positive and number <= 0.0:
        raise RuntimeError(f"Binance recovered {field} must be positive")
    if not positive and number < 0.0:
        raise RuntimeError(f"Binance recovered {field} cannot be negative")
    return number


def load_public_binance_closed_kline(
    symbol: str,
    timeframe: str,
    start_ms: int,
    *,
    now_ms: int | None = None,
    urlopen_fn=urlopen,
) -> dict[str, object]:
    """Load one exact already-closed Binance spot candle from the public API.

    This is a recovery primitive, not a history search. It refuses a nearby or
    still-open candle so the forward PAPER runtime can never silently substitute
    synthetic or ambiguous market data for a missed WebSocket close event.
    """

    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("Binance symbol is required")
    normalized_timeframe = str(timeframe).strip()
    width = timeframe_milliseconds(normalized_timeframe)
    requested_start = int(start_ms)
    if requested_start < 0:
        raise ValueError("kline start_ms cannot be negative")
    expected_close = requested_start + width - 1
    cutoff = int(now_ms if now_ms is not None else time.time() * 1_000)
    if cutoff < 0:
        raise ValueError("now_ms cannot be negative")

    query = urlencode(
        {
            "symbol": normalized_symbol,
            "interval": normalized_timeframe,
            "startTime": requested_start,
            "endTime": expected_close,
            "limit": 1,
        }
    )
    url = f"https://data-api.binance.vision/api/v3/klines?{query}"
    try:
        with urlopen_fn(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("public Binance closed candle could not be recovered") from exc

    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError("public Binance did not return the exact closed candle")
    row = payload[0]
    if not isinstance(row, list) or len(row) < 7:
        raise RuntimeError("public Binance exact closed candle payload is invalid")
    try:
        observed_start = int(row[0])
        observed_close = int(row[6])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("public Binance exact closed candle identity is invalid") from exc
    if observed_start != requested_start or observed_close != expected_close:
        raise RuntimeError("public Binance did not return the exact closed candle")
    if observed_close >= cutoff:
        raise RuntimeError("requested Binance candle is not closed yet")

    open_price = _finite_number(row[1], field="open", positive=True)
    high = _finite_number(row[2], field="high", positive=True)
    low = _finite_number(row[3], field="low", positive=True)
    close = _finite_number(row[4], field="close", positive=True)
    volume = _finite_number(row[5], field="volume", positive=False)
    if high < max(open_price, close) or low > min(open_price, close) or high < low:
        raise RuntimeError("Binance recovered OHLC values are inconsistent")

    return {
        "event_id": canonical_binance_kline_event_id(
            normalized_symbol,
            normalized_timeframe,
            requested_start,
        ),
        "venue": "BINANCE",
        "instrument": normalized_symbol,
        "timeframe": normalized_timeframe,
        "timestamp_ms": observed_close,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "source_kline_start_ms": observed_start,
        "source_kline_close_ms": observed_close,
        "recovered": True,
    }
