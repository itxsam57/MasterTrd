from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterator, Sequence
import json
from math import isfinite, log, sqrt
import time
from typing import Any, ContextManager, Protocol

from .streaming import RawMarketPayload


class _Connection(Protocol):
    def __iter__(self) -> Iterator[str | bytes]: ...


Connector = Callable[[str], ContextManager[_Connection]]


def _default_connector(uri: str) -> ContextManager[_Connection]:
    # websockets is already present in the locked execution stack through the
    # admitted runtime dependencies. Keep the import lazy so fixture-only test
    # and offline paths don't initialize networking code.
    from websockets.sync.client import connect

    return connect(
        uri,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
    )


def _canonical_symbol(value: str) -> str:
    raw = str(value).strip().upper()
    if not raw:
        raise ValueError("Binance stream symbol is required")
    if "." in raw:
        symbol, venue = raw.rsplit(".", 1)
        if venue != "BINANCE":
            raise ValueError("Binance public stream accepts only BINANCE instruments")
        raw = symbol
    if not raw or not raw.isalnum():
        raise ValueError("Binance stream symbol must be alphanumeric")
    return raw


def _positive_number(value: object, *, field: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Binance book ticker {field} must be numeric") from exc
    if not isfinite(numeric) or numeric <= 0.0:
        raise ValueError(f"Binance book ticker {field} must be positive and finite")
    return numeric


def _non_negative_number(value: object, *, field: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Binance kline {field} must be numeric") from exc
    if not isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"Binance kline {field} must be non-negative and finite")
    return numeric


def _json_payload(message: str | bytes) -> dict[str, object]:
    if isinstance(message, bytes):
        try:
            text = message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Binance stream message must be UTF-8") from exc
    elif isinstance(message, str):
        text = message
    else:
        raise ValueError("Binance stream message must be text or bytes")

    try:
        envelope: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Binance stream message contains invalid JSON") from exc
    if not isinstance(envelope, dict):
        raise ValueError("Binance stream message must be a JSON object")
    payload = envelope.get("data", envelope)
    if not isinstance(payload, dict):
        raise ValueError("Binance stream payload must be a JSON object")
    return payload


class BinancePublicBookTickerSource:
    """Synchronous public Binance best-bid/ask source with replay protection.

    The source emits canonical raw tick mappings consumed by ``MarketStream``.
    Transport failures reconnect with bounded backoff; malformed market data
    fails closed rather than being silently retried. Update IDs remain owned by
    the source across reconnects so replayed book-ticker updates cannot dispatch
    twice.
    """

    def __init__(
        self,
        instruments: Sequence[str],
        *,
        connector: Connector = _default_connector,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        reconnect_backoff_seconds: Sequence[float] = (1.0, 2.0, 5.0, 10.0, 30.0),
        max_reconnect_attempts: int | None = None,
        volatility_window: int = 30,
    ) -> None:
        symbols = tuple(dict.fromkeys(_canonical_symbol(value) for value in instruments))
        if not symbols:
            raise ValueError("at least one Binance instrument is required")
        if volatility_window < 2:
            raise ValueError("volatility_window must be at least 2")
        if max_reconnect_attempts is not None and max_reconnect_attempts < 0:
            raise ValueError("max_reconnect_attempts cannot be negative")
        backoff = tuple(float(value) for value in reconnect_backoff_seconds)
        if not backoff or any(not isfinite(value) or value < 0.0 for value in backoff):
            raise ValueError("reconnect backoff values must be finite and non-negative")

        self.symbols = symbols
        self._symbol_set = frozenset(symbols)
        self._connector = connector
        self._clock = clock
        self._sleep = sleep
        self._backoff = backoff
        self._max_reconnect_attempts = max_reconnect_attempts
        self._last_update_id: dict[str, int] = {}
        self._previous_midpoint: dict[str, float] = {}
        self._returns: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=volatility_window)
        )

    @property
    def uri(self) -> str:
        streams = "/".join(f"{symbol.lower()}@bookTicker" for symbol in self.symbols)
        return f"wss://data-stream.binance.com/stream?streams={streams}"

    def _decode(self, message: str | bytes) -> dict[str, object] | None:
        payload = _json_payload(message)

        try:
            symbol = _canonical_symbol(str(payload["s"]))
            update_id = int(payload["u"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Binance book ticker identity is invalid") from exc
        if symbol not in self._symbol_set:
            raise ValueError(f"unexpected Binance book ticker symbol: {symbol}")
        if update_id < 0:
            raise ValueError("Binance book ticker update ID cannot be negative")

        previous_update = self._last_update_id.get(symbol)
        if previous_update is not None and update_id <= previous_update:
            return None

        bid = _positive_number(payload.get("b"), field="bid")
        ask = _positive_number(payload.get("a"), field="ask")
        bid_size = _positive_number(payload.get("B"), field="bid_size")
        ask_size = _positive_number(payload.get("A"), field="ask_size")
        if ask < bid:
            raise ValueError("Binance book ticker ask cannot be below bid")

        midpoint = (bid + ask) / 2.0
        previous_midpoint = self._previous_midpoint.get(symbol)
        realized_volatility: float | None = None
        if previous_midpoint is not None:
            observed_return = log(midpoint / previous_midpoint)
            series = self._returns[symbol]
            series.append(observed_return)
            realized_volatility = sqrt(sum(value * value for value in series) / len(series))

        observed_at = float(self._clock())
        if not isfinite(observed_at) or observed_at < 0.0:
            raise ValueError("Binance stream clock must be finite and non-negative")

        self._last_update_id[symbol] = update_id
        self._previous_midpoint[symbol] = midpoint
        extras: dict[str, object] = {"source_update_id": update_id}
        if realized_volatility is not None:
            extras["realized_volatility"] = realized_volatility

        return {
            "event_id": f"binance-book:{symbol}:{update_id}",
            "venue": "BINANCE",
            "instrument": symbol,
            "timestamp_ms": observed_at * 1_000.0,
            "bid": bid,
            "ask": ask,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "last": midpoint,
            "last_size": 0.0,
            **extras,
        }

    def __iter__(self) -> Iterator[RawMarketPayload]:
        reconnects = 0
        while True:
            transport_failed = False
            try:
                with self._connector(self.uri) as connection:
                    for message in connection:
                        payload = self._decode(message)
                        if payload is not None:
                            yield payload
            except (OSError, TimeoutError):
                transport_failed = True

            if self._max_reconnect_attempts is not None and reconnects >= self._max_reconnect_attempts:
                return

            # A normal server close is reconnect-worthy for a persistent public
            # feed as well. Tests can set max_reconnect_attempts=0 for finite input.
            delay = self._backoff[min(reconnects, len(self._backoff) - 1)]
            reconnects += 1
            self._sleep(delay)

            # Keep the variable explicit so transport-vs-normal close behavior is
            # visible during debugging even though both reconnect by policy.
            del transport_failed


class BinancePublicMarketSource(BinancePublicBookTickerSource):
    """Combined Binance book-ticker and closed-kline source for forward PAPER.

    Book updates provide actual spread and observed midpoint volatility for the
    execution-risk state. Kline updates are emitted only after Binance marks the
    candle closed, so bar strategies never trade an in-progress candle. Both
    book update IDs and closed-candle identities survive reconnects to suppress
    replayed market events.
    """

    _SUPPORTED_INTERVALS = frozenset(
        {
            "1s",
            "1m",
            "3m",
            "5m",
            "15m",
            "30m",
            "1h",
            "2h",
            "4h",
            "6h",
            "8h",
            "12h",
            "1d",
            "3d",
            "1w",
            "1M",
        }
    )

    def __init__(
        self,
        instruments: Sequence[str],
        *,
        timeframe: str,
        connector: Connector = _default_connector,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        reconnect_backoff_seconds: Sequence[float] = (1.0, 2.0, 5.0, 10.0, 30.0),
        max_reconnect_attempts: int | None = None,
        volatility_window: int = 30,
    ) -> None:
        interval = str(timeframe).strip()
        if interval not in self._SUPPORTED_INTERVALS:
            raise ValueError(f"unsupported Binance kline timeframe: {timeframe}")
        super().__init__(
            instruments,
            connector=connector,
            clock=clock,
            sleep=sleep,
            reconnect_backoff_seconds=reconnect_backoff_seconds,
            max_reconnect_attempts=max_reconnect_attempts,
            volatility_window=volatility_window,
        )
        self.timeframe = interval
        self._last_closed_kline_start: dict[str, int] = {}
        self._latest_spread_bps: dict[str, float] = {}
        self._latest_realized_volatility: dict[str, float] = {}

    @property
    def uri(self) -> str:
        streams: list[str] = []
        for symbol in self.symbols:
            lowered = symbol.lower()
            streams.append(f"{lowered}@bookTicker")
            streams.append(f"{lowered}@kline_{self.timeframe}")
        return "wss://data-stream.binance.com/stream?streams=" + "/".join(streams)

    def _decode_kline(self, payload: dict[str, object]) -> dict[str, object] | None:
        raw_kline = payload.get("k")
        if not isinstance(raw_kline, dict):
            raise ValueError("Binance kline payload must contain a kline object")

        try:
            symbol = _canonical_symbol(str(raw_kline["s"]))
            interval = str(raw_kline["i"])
            start_ms = int(raw_kline["t"])
            close_ms = int(raw_kline["T"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Binance kline identity is invalid") from exc
        if symbol not in self._symbol_set:
            raise ValueError(f"unexpected Binance kline symbol: {symbol}")
        if interval != self.timeframe:
            raise ValueError(f"unexpected Binance kline interval: {interval}")
        if start_ms < 0 or close_ms < start_ms:
            raise ValueError("Binance kline timestamps are invalid")

        closed = raw_kline.get("x")
        if not isinstance(closed, bool):
            raise ValueError("Binance kline closed flag must be boolean")
        if not closed:
            return None

        previous_start = self._last_closed_kline_start.get(symbol)
        if previous_start is not None and start_ms <= previous_start:
            return None

        open_price = _positive_number(raw_kline.get("o"), field="open")
        high = _positive_number(raw_kline.get("h"), field="high")
        low = _positive_number(raw_kline.get("l"), field="low")
        close = _positive_number(raw_kline.get("c"), field="close")
        volume = _non_negative_number(raw_kline.get("v"), field="volume")
        if high < max(open_price, close) or low > min(open_price, close) or high < low:
            raise ValueError("Binance kline OHLC values are inconsistent")

        self._last_closed_kline_start[symbol] = start_ms
        extras: dict[str, object] = {
            "source_kline_start_ms": start_ms,
            "source_kline_close_ms": close_ms,
        }
        spread_bps = self._latest_spread_bps.get(symbol)
        if spread_bps is not None:
            extras["spread_bps"] = spread_bps
        realized_volatility = self._latest_realized_volatility.get(symbol)
        if realized_volatility is not None:
            extras["realized_volatility"] = realized_volatility

        return {
            "event_id": f"binance-kline:{symbol}:{interval}:{start_ms}",
            "venue": "BINANCE",
            "instrument": symbol,
            "timeframe": interval,
            "timestamp_ms": close_ms,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            **extras,
        }

    def _decode(self, message: str | bytes) -> dict[str, object] | None:
        payload = _json_payload(message)
        if payload.get("e") == "kline" or "k" in payload:
            return self._decode_kline(payload)

        decoded = super()._decode(message)
        if decoded is None:
            return None
        symbol = str(decoded["instrument"])
        bid = float(decoded["bid"])
        ask = float(decoded["ask"])
        midpoint = (bid + ask) / 2.0
        self._latest_spread_bps[symbol] = ((ask - bid) / midpoint) * 10_000.0
        volatility = decoded.get("realized_volatility")
        if volatility is not None:
            self._latest_realized_volatility[symbol] = float(volatility)
        return decoded
