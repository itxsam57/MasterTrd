from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from math import isfinite
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from .streaming import MarketStream, MarketStreamEvent


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


@dataclass(frozen=True, slots=True)
class BarCompletenessSnapshot:
    expected_closed_bars: int
    ws_closed_bars: int
    rest_recovered_bars: int
    missing_closed_bars: int
    recovery_failures: int
    last_closed_bar_ms: int | None
    last_expected_close_ms: int | None
    last_recovery_error: str | None
    data_healthy: bool


RecoveryLoader = Callable[..., Mapping[str, object]]


class ClosedBarCompletenessTracker:
    """Track and recover the exact closed bars a forward PAPER session expects."""

    def __init__(
        self,
        *,
        instruments: Sequence[str],
        timeframe: str,
        first_expected_start_ms: int,
        recovery_loader: RecoveryLoader = load_public_binance_closed_kline,
        grace_ms: int = 5_000,
        retry_interval_ms: int = 30_000,
    ) -> None:
        normalized = tuple(str(item).strip().upper() for item in instruments)
        if not normalized or any(not item for item in normalized):
            raise ValueError("at least one Binance instrument is required")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Binance completeness instruments must be unique")
        self.instruments = normalized
        self.timeframe = str(timeframe).strip()
        self._width_ms = timeframe_milliseconds(self.timeframe)
        self._first_expected_start_ms = int(first_expected_start_ms)
        if self._first_expected_start_ms < 0:
            raise ValueError("first_expected_start_ms cannot be negative")
        if self._first_expected_start_ms % self._width_ms != 0:
            raise ValueError("first expected candle must align to the timeframe boundary")
        if grace_ms < 0:
            raise ValueError("grace_ms cannot be negative")
        if retry_interval_ms <= 0:
            raise ValueError("retry_interval_ms must be positive")
        self._grace_ms = int(grace_ms)
        self._retry_interval_ms = int(retry_interval_ms)
        self._recovery_loader = recovery_loader

        self._next_expected_start_ms = self._first_expected_start_ms
        self._expected: dict[str, tuple[str, int]] = {}
        self._received: set[str] = set()
        self._ws_received: set[str] = set()
        self._rest_recovered: set[str] = set()
        self._missing: set[str] = set()
        self._next_retry_ms: dict[str, int] = {}
        self._recovery_failures = 0
        self._last_closed_bar_ms: int | None = None
        self._last_expected_close_ms: int | None = None
        self._last_recovery_error: str | None = None

    @property
    def snapshot(self) -> BarCompletenessSnapshot:
        return BarCompletenessSnapshot(
            expected_closed_bars=len(self._expected),
            ws_closed_bars=len(self._ws_received),
            rest_recovered_bars=len(self._rest_recovered),
            missing_closed_bars=len(self._missing),
            recovery_failures=self._recovery_failures,
            last_closed_bar_ms=self._last_closed_bar_ms,
            last_expected_close_ms=self._last_expected_close_ms,
            last_recovery_error=self._last_recovery_error,
            data_healthy=not self._missing,
        )

    def _register_due(self, observed_ms: int) -> None:
        observed = int(observed_ms)
        first_due_boundary = self._next_expected_start_ms + self._width_ms + self._grace_ms
        if observed < first_due_boundary:
            return
        effective = observed - self._grace_ms
        last_due_start = expected_closed_start_ms(
            observed_ms=effective,
            timeframe=self.timeframe,
        )
        while self._next_expected_start_ms <= last_due_start:
            start_ms = self._next_expected_start_ms
            close_ms = start_ms + self._width_ms - 1
            for symbol in self.instruments:
                event_id = canonical_binance_kline_event_id(symbol, self.timeframe, start_ms)
                self._expected[event_id] = (symbol, start_ms)
                if event_id not in self._received:
                    self._missing.add(event_id)
            self._last_expected_close_ms = close_ms
            self._next_expected_start_ms += self._width_ms

    def observe(self, event: MarketStreamEvent) -> None:
        if event.kind != "bar":
            return
        bar = event.bar
        symbol = str(bar.instrument).strip().upper()
        if bar.venue != "BINANCE" or symbol not in self.instruments or bar.timeframe != self.timeframe:
            return
        try:
            start_ms = int(bar.extras["source_kline_start_ms"])
            close_ms = int(bar.extras["source_kline_close_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Binance closed bar is missing source kline identity") from exc
        expected_id = canonical_binance_kline_event_id(symbol, self.timeframe, start_ms)
        if event.event_id != expected_id:
            raise ValueError("Binance closed bar event identity is inconsistent")
        if close_ms != start_ms + self._width_ms - 1:
            raise ValueError("Binance closed bar close boundary is inconsistent")
        if event.event_id in self._received:
            return

        self._received.add(event.event_id)
        self._missing.discard(event.event_id)
        self._next_retry_ms.pop(event.event_id, None)
        if bool(bar.extras.get("recovered", False)):
            self._rest_recovered.add(event.event_id)
        else:
            self._ws_received.add(event.event_id)
        self._last_closed_bar_ms = max(self._last_closed_bar_ms or close_ms, close_ms)
        if not self._missing:
            self._last_recovery_error = None

    def recover_due(self, observed_ms: int) -> tuple[Mapping[str, object], ...]:
        observed = int(observed_ms)
        if observed < 0:
            raise ValueError("observed_ms cannot be negative")
        self._register_due(observed)

        recovered: list[Mapping[str, object]] = []
        ordered = sorted(
            (
                (event_id, symbol, start_ms)
                for event_id, (symbol, start_ms) in self._expected.items()
                if event_id not in self._received
            ),
            key=lambda item: (item[2], item[1]),
        )
        for event_id, symbol, start_ms in ordered:
            next_retry = self._next_retry_ms.get(event_id, 0)
            if observed < next_retry:
                continue
            try:
                payload = self._recovery_loader(
                    symbol,
                    self.timeframe,
                    start_ms,
                    now_ms=observed,
                )
                event = MarketStream.normalize(payload)
                if event.event_id != event_id:
                    raise RuntimeError("recovery returned the wrong closed candle identity")
                if event.kind != "bar" or not bool(event.bar.extras.get("recovered", False)):
                    raise RuntimeError("recovery did not return an authoritative recovered bar")
                self.observe(event)
            except Exception as exc:
                self._missing.add(event_id)
                self._next_retry_ms[event_id] = observed + self._retry_interval_ms
                self._recovery_failures += 1
                self._last_recovery_error = f"{type(exc).__name__}:{exc}"
                continue
            recovered.append(payload)
        return tuple(recovered)
