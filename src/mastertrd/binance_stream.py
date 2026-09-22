from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterator, Mapping, Sequence
import json
from math import isfinite, log, sqrt
import time
from typing import Any, ContextManager, Protocol

from .bar_completeness import (
    BarCompletenessSnapshot,
    ClosedBarCompletenessTracker,
    RecoveryLoader,
    load_public_binance_closed_kline,
)
from .streaming import MarketStream, RawMarketPayload


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
        return f"wss://data-stream.binance.vision/stream?streams={streams}"

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

    def _ready_payloads(self, payload: RawMarketPayload) -> Iterator[RawMarketPayload]:
        """Yield decoded payloads in dispatch order.

        Subclasses can inject authoritative events which must precede the just-
        decoded current payload without duplicating transport/reconnect logic.
        """

        yield payload

    def __iter__(self) -> Iterator[RawMarketPayload]:
        # ``websockets`` is an execution-stack dependency and is intentionally
        # imported only when the network iterator is used. Connection closures
        # are transport failures; malformed payload/data exceptions still escape
        # and fail closed rather than being misclassified as reconnectable.
        from websockets.exceptions import ConnectionClosed

        reconnects = 0
        while True:
            transport_failed = False
            try:
                with self._connector(self.uri) as connection:
                    for message in connection:
                        payload = self._decode(message)
                        if payload is not None:
                            yield from self._ready_payloads(payload)
            except (OSError, TimeoutError, ConnectionClosed):
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

    A portfolio may request one or several kline intervals. Book ticker is
    subscribed once per symbol; klines are subscribed only for configured
    symbol/timeframe pairs. Completeness recovery remains independent per
    timeframe so missing closed bars fail closed without weakening other lanes.
    """

    _SUPPORTED_INTERVALS = frozenset(
        {
            "1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h",
            "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M",
        }
    )

    def __init__(
        self,
        instruments: Sequence[str],
        *,
        timeframe: str | Sequence[str],
        subscriptions: Mapping[str, Sequence[str]] | None = None,
        connector: Connector = _default_connector,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        reconnect_backoff_seconds: Sequence[float] = (1.0, 2.0, 5.0, 10.0, 30.0),
        max_reconnect_attempts: int | None = None,
        volatility_window: int = 30,
        first_expected_start_ms: int | Mapping[str, int] | None = None,
        recovery_loader: RecoveryLoader = load_public_binance_closed_kline,
        recovery_grace_ms: int = 0,
        recovery_retry_interval_ms: int = 30_000,
    ) -> None:
        if isinstance(timeframe, str):
            intervals = (timeframe.strip(),)
        else:
            intervals = tuple(dict.fromkeys(str(value).strip() for value in timeframe))
        if not intervals or any(interval not in self._SUPPORTED_INTERVALS for interval in intervals):
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
        self.timeframes = intervals
        self.timeframe = intervals[0] if len(intervals) == 1 else None

        if subscriptions is None:
            by_timeframe = {interval: self.symbols for interval in intervals}
        else:
            if set(subscriptions) != set(intervals):
                raise ValueError("Binance portfolio subscriptions must cover every configured timeframe")
            by_timeframe: dict[str, tuple[str, ...]] = {}
            for interval in intervals:
                values = tuple(
                    dict.fromkeys(_canonical_symbol(value) for value in subscriptions[interval])
                )
                if not values:
                    raise ValueError("each Binance timeframe requires at least one instrument")
                if set(values) - self._symbol_set:
                    raise ValueError("Binance timeframe subscription contains an unknown instrument")
                by_timeframe[interval] = values
        self._symbols_by_timeframe = by_timeframe
        self._symbol_sets_by_timeframe = {
            interval: frozenset(values) for interval, values in by_timeframe.items()
        }
        self._last_closed_kline_start: dict[tuple[str, str], int] = {}
        self._latest_spread_bps: dict[str, float] = {}
        self._latest_realized_volatility: dict[str, float] = {}
        self._completeness_by_timeframe: dict[str, ClosedBarCompletenessTracker] = {}
        self._completeness: ClosedBarCompletenessTracker | None = None

        if first_expected_start_ms is not None:
            if isinstance(first_expected_start_ms, Mapping):
                anchors = {str(key): int(value) for key, value in first_expected_start_ms.items()}
                if set(anchors) != set(intervals):
                    raise ValueError("closed-bar completeness anchors must cover every timeframe")
            else:
                if len(intervals) != 1:
                    raise ValueError("multi-timeframe PAPER requires one completeness anchor per timeframe")
                anchors = {intervals[0]: int(first_expected_start_ms)}
            for interval in intervals:
                self._completeness_by_timeframe[interval] = ClosedBarCompletenessTracker(
                    instruments=self._symbols_by_timeframe[interval],
                    timeframe=interval,
                    first_expected_start_ms=anchors[interval],
                    recovery_loader=recovery_loader,
                    grace_ms=int(recovery_grace_ms),
                    retry_interval_ms=int(recovery_retry_interval_ms),
                )
        if len(self.timeframes) == 1:
            self._completeness = self._completeness_by_timeframe.get(self.timeframes[0])

    @property
    def completeness_snapshot(self) -> BarCompletenessSnapshot | None:
        if len(self.timeframes) != 1:
            return None
        tracker = self._completeness
        return None if tracker is None else tracker.snapshot

    @property
    def completeness_snapshots(self) -> Mapping[str, BarCompletenessSnapshot]:
        return {
            interval: tracker.snapshot
            for interval, tracker in self._completeness_by_timeframe.items()
        }

    @property
    def uri(self) -> str:
        streams: list[str] = [f"{symbol.lower()}@bookTicker" for symbol in self.symbols]
        for interval in self.timeframes:
            streams.extend(
                f"{symbol.lower()}@kline_{interval}"
                for symbol in self._symbols_by_timeframe[interval]
            )
        return "wss://data-stream.binance.vision/stream?streams=" + "/".join(streams)

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
        if interval not in self._symbol_sets_by_timeframe:
            raise ValueError(f"unexpected Binance kline interval: {interval}")
        if symbol not in self._symbol_sets_by_timeframe[interval]:
            raise ValueError(f"unexpected Binance kline symbol: {symbol}")
        if start_ms < 0 or close_ms < start_ms:
            raise ValueError("Binance kline timestamps are invalid")

        closed = raw_kline.get("x")
        if not isinstance(closed, bool):
            raise ValueError("Binance kline closed flag must be boolean")
        if not closed:
            return None

        identity = (symbol, interval)
        previous_start = self._last_closed_kline_start.get(identity)
        if previous_start is not None and start_ms <= previous_start:
            return None

        open_price = _positive_number(raw_kline.get("o"), field="open")
        high = _positive_number(raw_kline.get("h"), field="high")
        low = _positive_number(raw_kline.get("l"), field="low")
        close = _positive_number(raw_kline.get("c"), field="close")
        volume = _non_negative_number(raw_kline.get("v"), field="volume")
        if high < max(open_price, close) or low > min(open_price, close) or high < low:
            raise ValueError("Binance kline OHLC values are inconsistent")

        self._last_closed_kline_start[identity] = start_ms
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

    def _enrich_recovered_bar(self, payload: Mapping[str, object]) -> dict[str, object]:
        recovered = dict(payload)
        symbol = _canonical_symbol(str(recovered.get("instrument", "")))
        interval = str(recovered.get("timeframe", ""))
        if interval not in self._symbol_sets_by_timeframe:
            raise RuntimeError("closed-bar recovery returned an unexpected timeframe")
        if symbol not in self._symbol_sets_by_timeframe[interval]:
            raise RuntimeError("closed-bar recovery returned an unexpected Binance symbol")

        spread_bps = self._latest_spread_bps.get(symbol)
        if spread_bps is not None:
            recovered["spread_bps"] = spread_bps
        realized_volatility = self._latest_realized_volatility.get(symbol)
        if realized_volatility is not None:
            recovered["realized_volatility"] = realized_volatility
        return recovered

    def _ready_payloads(self, payload: RawMarketPayload) -> Iterator[RawMarketPayload]:
        if not self._completeness_by_timeframe:
            yield payload
            return

        normalized = MarketStream.normalize(payload)
        if normalized.kind == "bar":
            tracker = self._completeness_by_timeframe.get(normalized.bar.timeframe)
            if tracker is not None:
                tracker.observe(normalized)
            yield payload
            return

        observed_ms = int(float(payload["timestamp_ms"]))
        for interval in self.timeframes:
            tracker = self._completeness_by_timeframe.get(interval)
            if tracker is None:
                continue
            recovered = tracker.recover_due(observed_ms)
            for raw in recovered:
                enriched = self._enrich_recovered_bar(raw)
                symbol = str(enriched["instrument"])
                recovered_interval = str(enriched["timeframe"])
                start_ms = int(enriched["source_kline_start_ms"])
                identity = (symbol, recovered_interval)
                previous_start = self._last_closed_kline_start.get(identity)
                if previous_start is None or start_ms > previous_start:
                    self._last_closed_kline_start[identity] = start_ms
                yield enriched

            snapshot = tracker.snapshot
            if not snapshot.data_healthy:
                detail = snapshot.last_recovery_error or "authoritative candle unavailable"
                raise RuntimeError(f"closed-bar recovery failed: {detail}")
        yield payload
