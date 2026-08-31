import json

from mastertrd.binance_stream import BinancePublicBookTickerSource
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
