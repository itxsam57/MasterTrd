from datetime import datetime, timezone

import pytest

from mastertrd.streaming import MarketStream, MarketStreamEvent


def bar_payload(event_id: str, timestamp_ms: int) -> dict[str, object]:
    return {
        "event_id": event_id,
        "venue": "BINANCE",
        "instrument": "ETHUSDT",
        "timeframe": "1m",
        "timestamp_ms": timestamp_ms,
        "open": "2000.0",
        "high": "2010.0",
        "low": "1995.0",
        "close": "2005.0",
        "volume": "12.5",
    }


def test_market_stream_normalizes_public_bar_payload_to_canonical_contract():
    raw = bar_payload("binance:ethusdt:1m:1000", 1_700_000_000_000)

    event = MarketStream.normalize_bar(raw)

    assert isinstance(event, MarketStreamEvent)
    assert event.event_id == raw["event_id"]
    assert event.kind == "bar"
    assert event.bar.timestamp == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert event.bar.venue == "BINANCE"
    assert event.bar.instrument == "ETHUSDT"
    assert event.bar.close == 2005.0


def test_market_stream_normalizes_tick_payload_and_rejects_crossed_book():
    raw = {
        "event_id": "tick-1",
        "venue": "BINANCE",
        "instrument": "ETHUSDT",
        "timestamp_ms": 1_700_000_000_001,
        "bid": "2004.5",
        "ask": "2005.0",
        "bid_size": "3.0",
        "ask_size": "4.0",
        "last": "2004.8",
        "last_size": "0.5",
    }

    event = MarketStream.normalize_tick(raw)

    assert event.kind == "tick"
    assert event.tick.bid == 2004.5
    assert event.tick.ask == 2005.0
    assert event.tick.last == 2004.8

    crossed = dict(raw, event_id="tick-crossed", bid="2006", ask="2005")
    with pytest.raises(ValueError, match="crossed"):
        MarketStream.normalize_tick(crossed)


def test_market_stream_reconnect_source_replays_identity_for_runtime_deduplication():
    first = MarketStream([bar_payload("e1", 1_700_000_000_000)])
    second = first.reconnect(
        [
            bar_payload("e1", 1_700_000_000_000),
            bar_payload("e2", 1_700_000_060_000),
        ]
    )

    assert [event.event_id for event in first] == ["e1"]
    assert [event.event_id for event in second] == ["e1", "e2"]


def test_market_stream_fails_closed_on_missing_identity_or_bad_timestamp():
    missing_id = bar_payload("unused", 1)
    del missing_id["event_id"]
    with pytest.raises(ValueError, match="event_id"):
        MarketStream.normalize_bar(missing_id)

    bad_time = bar_payload("bad-time", 1)
    bad_time["timestamp_ms"] = "bad"
    with pytest.raises(ValueError, match="timestamp_ms"):
        MarketStream.normalize_bar(bad_time)
