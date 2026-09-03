from __future__ import annotations


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
