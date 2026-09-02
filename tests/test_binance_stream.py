import json

from websockets.exceptions import ConnectionClosedError

from mastertrd.binance_stream import (
    BinancePublicBookTickerSource,
    BinancePublicMarketSource,
)
from mastertrd.streaming import MarketStream


class FakeConnection:
    def __init__(self, messages):
        self._messages = messages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def __iter__(self):
        for message in self._messages:
            if isinstance(message, BaseException):
                raise message
            yield message


def combined(symbol: str, update_id: int, bid: str, ask: str) -> str:
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@bookTicker",
            "data": {
                "u": update_id,
                "s": symbol,
                "b": bid,
                "B": "2.5",
                "a": ask,
                "A": "3.0",
            },
        }
    )


def kline(
    symbol: str,
    timeframe: str,
    start_ms: int,
    close_ms: int,
    *,
    open_price: str,
    high: str,
    low: str,
    close: str,
    volume: str,
    closed: bool,
) -> str:
    return json.dumps(
        {
            "stream": f"{symbol.lower()}@kline_{timeframe}",
            "data": {
                "e": "kline",
                "E": close_ms,
                "s": symbol,
                "k": {
                    "t": start_ms,
                    "T": close_ms,
                    "s": symbol,
                    "i": timeframe,
                    "o": open_price,
                    "h": high,
                    "l": low,
                    "c": close,
                    "v": volume,
                    "x": closed,
                },
            },
        }
    )


def test_book_ticker_source_normalizes_deduplicates_and_adds_observed_volatility():
    connections = iter(
        [
            FakeConnection(
                [
                    combined("ETHUSDT", 10, "2000", "2002"),
                    combined("ETHUSDT", 10, "2000", "2002"),
                    combined("ETHUSDT", 11, "2004", "2006"),
                    combined("ETHUSDT", 12, "1998", "2000"),
                ]
            )
        ]
    )
    times = iter([1_700_000_000.000, 1_700_000_001.000, 1_700_000_002.000])
    source = BinancePublicBookTickerSource(
        ("ETHUSDT.BINANCE",),
        connector=lambda _uri: next(connections),
        clock=lambda: next(times),
        max_reconnect_attempts=0,
    )

    events = list(MarketStream(source))

    assert [event.event_id for event in events] == [
        "binance-book:ETHUSDT:10",
        "binance-book:ETHUSDT:11",
        "binance-book:ETHUSDT:12",
    ]
    assert all(event.kind == "tick" for event in events)
    assert events[0].tick.venue == "BINANCE"
    assert events[0].tick.instrument == "ETHUSDT"
    assert events[0].tick.bid == 2000.0
    assert events[0].tick.ask == 2002.0
    assert "realized_volatility" not in events[0].tick.extras
    assert events[1].tick.extras["realized_volatility"] > 0.0
    assert events[2].tick.extras["realized_volatility"] > 0.0


def test_book_ticker_source_reconnects_with_backoff_and_keeps_update_identity():
    connections = iter(
        [
            FakeConnection([combined("BTCUSDT", 20, "50000", "50002"), OSError("drop")]),
            FakeConnection([combined("BTCUSDT", 20, "50000", "50002"), combined("BTCUSDT", 21, "50003", "50005")]),
        ]
    )
    sleeps: list[float] = []
    times = iter([1_700_100_000.0, 1_700_100_001.0])
    source = BinancePublicBookTickerSource(
        ("BTCUSDT.BINANCE",),
        connector=lambda _uri: next(connections),
        clock=lambda: next(times),
        sleep=lambda seconds: sleeps.append(seconds),
        reconnect_backoff_seconds=(0.25, 0.5),
        max_reconnect_attempts=1,
    )

    events = list(MarketStream(source))

    assert [event.event_id for event in events] == [
        "binance-book:BTCUSDT:20",
        "binance-book:BTCUSDT:21",
    ]
    assert sleeps == [0.25]


def test_book_ticker_source_reconnects_on_websocket_connection_closed_error():
    connections = iter(
        [
            FakeConnection(
                [
                    combined("ETHUSDT", 40, "2100", "2102"),
                    ConnectionClosedError(None, None),
                ]
            ),
            FakeConnection(
                [
                    combined("ETHUSDT", 40, "2100", "2102"),
                    combined("ETHUSDT", 41, "2103", "2105"),
                ]
            ),
        ]
    )
    sleeps: list[float] = []
    times = iter([1_700_150_000.0, 1_700_150_001.0])
    source = BinancePublicBookTickerSource(
        ("ETHUSDT.BINANCE",),
        connector=lambda _uri: next(connections),
        clock=lambda: next(times),
        sleep=lambda seconds: sleeps.append(seconds),
        reconnect_backoff_seconds=(0.25, 0.5),
        max_reconnect_attempts=1,
    )

    events = list(MarketStream(source))

    assert [event.event_id for event in events] == [
        "binance-book:ETHUSDT:40",
        "binance-book:ETHUSDT:41",
    ]
    assert sleeps == [0.25]


def test_public_market_source_emits_only_closed_klines_with_live_spread_and_volatility():
    start_ms = 1_700_200_000_000
    close_ms = start_ms + 59_999
    connections = iter(
        [
            FakeConnection(
                [
                    combined("ETHUSDT", 30, "2000", "2002"),
                    combined("ETHUSDT", 31, "2004", "2006"),
                    kline(
                        "ETHUSDT",
                        "1m",
                        start_ms,
                        close_ms,
                        open_price="2000",
                        high="2010",
                        low="1995",
                        close="2005",
                        volume="10",
                        closed=False,
                    ),
                    kline(
                        "ETHUSDT",
                        "1m",
                        start_ms,
                        close_ms,
                        open_price="2000",
                        high="2010",
                        low="1995",
                        close="2005",
                        volume="10",
                        closed=True,
                    ),
                ]
            )
        ]
    )
    times = iter([1_700_200_000.000, 1_700_200_001.000])
    source = BinancePublicMarketSource(
        ("ETHUSDT.BINANCE",),
        timeframe="1m",
        connector=lambda _uri: next(connections),
        clock=lambda: next(times),
        max_reconnect_attempts=0,
    )

    events = list(MarketStream(source))

    assert [event.event_id for event in events] == [
        "binance-book:ETHUSDT:30",
        "binance-book:ETHUSDT:31",
        f"binance-kline:ETHUSDT:1m:{start_ms}",
    ]
    bar = events[-1].bar
    assert bar.instrument == "ETHUSDT"
    assert bar.venue == "BINANCE"
    assert bar.timeframe == "1m"
    assert bar.open == 2000.0
    assert bar.high == 2010.0
    assert bar.low == 1995.0
    assert bar.close == 2005.0
    assert bar.volume == 10.0
    assert bar.extras["spread_bps"] > 0.0
    assert bar.extras["realized_volatility"] > 0.0


def test_public_market_source_reconnect_deduplicates_closed_klines():
    first_start = 1_700_300_000_000
    second_start = first_start + 60_000
    first = kline(
        "BTCUSDT",
        "1m",
        first_start,
        first_start + 59_999,
        open_price="50000",
        high="50010",
        low="49990",
        close="50005",
        volume="1",
        closed=True,
    )
    second = kline(
        "BTCUSDT",
        "1m",
        second_start,
        second_start + 59_999,
        open_price="50005",
        high="50020",
        low="50000",
        close="50015",
        volume="1",
        closed=True,
    )
    connections = iter(
        [
            FakeConnection([first, OSError("drop")]),
            FakeConnection([first, second]),
        ]
    )
    sleeps: list[float] = []
    source = BinancePublicMarketSource(
        ("BTCUSDT.BINANCE",),
        timeframe="1m",
        connector=lambda _uri: next(connections),
        sleep=lambda seconds: sleeps.append(seconds),
        reconnect_backoff_seconds=(0.25, 0.5),
        max_reconnect_attempts=1,
    )

    bars = [event for event in MarketStream(source) if event.kind == "bar"]

    assert [event.event_id for event in bars] == [
        f"binance-kline:BTCUSDT:1m:{first_start}",
        f"binance-kline:BTCUSDT:1m:{second_start}",
    ]
    assert sleeps == [0.25]
