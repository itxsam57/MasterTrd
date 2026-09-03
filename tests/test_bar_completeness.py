import json

import pytest

from mastertrd.bar_completeness import (
    ClosedBarCompletenessTracker,
    canonical_binance_kline_event_id,
    expected_closed_start_ms,
    load_public_binance_closed_kline,
    timeframe_milliseconds,
)
from mastertrd.streaming import MarketStream


class FakeResponse:
    def __init__(self, payload: object):
        self._content = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def recovered_bar_payload(start_ms: int, timeframe: str = "4h") -> dict[str, object]:
    close_ms = start_ms + timeframe_milliseconds(timeframe) - 1
    return {
        "event_id": canonical_binance_kline_event_id("ETHUSDT", timeframe, start_ms),
        "venue": "BINANCE",
        "instrument": "ETHUSDT",
        "timeframe": timeframe,
        "timestamp_ms": close_ms,
        "open": 2000.0,
        "high": 2010.0,
        "low": 1990.0,
        "close": 2005.0,
        "volume": 10.0,
        "source_kline_start_ms": start_ms,
        "source_kline_close_ms": close_ms,
        "recovered": True,
    }


def test_four_hour_boundary_maps_to_previous_closed_candle():
    assert timeframe_milliseconds("4h") == 14_400_000
    assert expected_closed_start_ms(
        observed_ms=1_788_436_805_000,
        timeframe="4h",
    ) == 1_788_422_400_000


def test_canonical_kline_identity_matches_websocket_contract():
    assert canonical_binance_kline_event_id(
        "ethusdt",
        "4h",
        1_788_422_400_000,
    ) == "binance-kline:ETHUSDT:4h:1788422400000"


def test_closed_bar_schedule_rejects_unsupported_variable_month_interval():
    with pytest.raises(ValueError, match="unsupported fixed Binance timeframe"):
        timeframe_milliseconds("1M")


def test_schedule_and_identity_reject_invalid_boundaries():
    with pytest.raises(ValueError, match="too early"):
        expected_closed_start_ms(observed_ms=59_999, timeframe="1m")
    with pytest.raises(ValueError, match="symbol is required"):
        canonical_binance_kline_event_id(" ", "1m", 0)
    with pytest.raises(ValueError, match="cannot be negative"):
        canonical_binance_kline_event_id("ETHUSDT", "1m", -1)


def test_rest_recovery_requires_exact_requested_closed_candle():
    start_ms = 1_788_422_400_000
    close_ms = 1_788_436_799_999
    row = [start_ms, "2000", "2010", "1990", "2005", "10", close_ms]
    requested_urls: list[str] = []

    def open_response(url: str, **_kwargs):
        requested_urls.append(url)
        return FakeResponse([row])

    payload = load_public_binance_closed_kline(
        "ETHUSDT",
        "4h",
        start_ms,
        now_ms=close_ms + 5_001,
        urlopen_fn=open_response,
    )

    assert payload["event_id"] == "binance-kline:ETHUSDT:4h:1788422400000"
    assert payload["venue"] == "BINANCE"
    assert payload["instrument"] == "ETHUSDT"
    assert payload["timeframe"] == "4h"
    assert payload["close"] == 2005.0
    assert payload["source_kline_start_ms"] == start_ms
    assert payload["source_kline_close_ms"] == close_ms
    assert payload["recovered"] is True
    assert "startTime=1788422400000" in requested_urls[0]
    assert "endTime=1788436799999" in requested_urls[0]
    assert "limit=1" in requested_urls[0]


def test_rest_recovery_fails_closed_on_wrong_candle_identity():
    requested_start = 1_788_422_400_000
    wrong_start = requested_start - 14_400_000
    wrong_close = requested_start - 1
    row = [wrong_start, "2000", "2010", "1990", "2005", "10", wrong_close]

    with pytest.raises(RuntimeError, match="exact closed candle"):
        load_public_binance_closed_kline(
            "ETHUSDT",
            "4h",
            requested_start,
            now_ms=1_788_436_805_000,
            urlopen_fn=lambda *_args, **_kwargs: FakeResponse([row]),
        )


def test_rest_recovery_fails_closed_when_requested_candle_is_not_closed_yet():
    start_ms = 1_788_422_400_000
    close_ms = 1_788_436_799_999
    row = [start_ms, "2000", "2010", "1990", "2005", "10", close_ms]

    with pytest.raises(RuntimeError, match="not closed"):
        load_public_binance_closed_kline(
            "ETHUSDT",
            "4h",
            start_ms,
            now_ms=close_ms,
            urlopen_fn=lambda *_args, **_kwargs: FakeResponse([row]),
        )


def test_rest_recovery_rejects_invalid_ohlc():
    start_ms = 1_788_422_400_000
    close_ms = 1_788_436_799_999
    row = [start_ms, "2000", "1999", "1990", "2005", "10", close_ms]

    with pytest.raises(RuntimeError, match="OHLC"):
        load_public_binance_closed_kline(
            "ETHUSDT",
            "4h",
            start_ms,
            now_ms=close_ms + 1,
            urlopen_fn=lambda *_args, **_kwargs: FakeResponse([row]),
        )


def test_rest_recovery_rejects_invalid_request_and_transport():
    with pytest.raises(ValueError, match="symbol is required"):
        load_public_binance_closed_kline(" ", "1m", 0, now_ms=100_000)
    with pytest.raises(ValueError, match="start_ms cannot be negative"):
        load_public_binance_closed_kline("ETHUSDT", "1m", -1, now_ms=100_000)
    with pytest.raises(ValueError, match="now_ms cannot be negative"):
        load_public_binance_closed_kline("ETHUSDT", "1m", 0, now_ms=-1)

    def offline(*_args, **_kwargs):
        raise OSError("offline")

    with pytest.raises(RuntimeError, match="could not be recovered"):
        load_public_binance_closed_kline(
            "ETHUSDT",
            "1m",
            0,
            now_ms=60_001,
            urlopen_fn=offline,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "exact closed candle"),
        ([[0, "1"]], "payload is invalid"),
        ([["bad", "1", "1", "1", "1", "1", "bad"]], "identity is invalid"),
    ],
)
def test_rest_recovery_rejects_malformed_payloads(payload, message):
    with pytest.raises(RuntimeError, match=message):
        load_public_binance_closed_kline(
            "ETHUSDT",
            "1m",
            0,
            now_ms=60_001,
            urlopen_fn=lambda *_args, **_kwargs: FakeResponse(payload),
        )


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (1, "bad", "open is invalid"),
        (2, "nan", "high must be finite"),
        (3, "0", "low must be positive"),
        (5, "-1", "volume cannot be negative"),
    ],
)
def test_rest_recovery_rejects_invalid_numeric_fields(index, value, message):
    start_ms = 0
    row = [start_ms, "1", "2", "0.5", "1.5", "10", 59_999]
    row[index] = value
    with pytest.raises(RuntimeError, match=message):
        load_public_binance_closed_kline(
            "ETHUSDT",
            "1m",
            start_ms,
            now_ms=60_001,
            urlopen_fn=lambda *_args, **_kwargs: FakeResponse([row]),
        )


def test_missing_expected_bar_is_recovered_once_and_late_ws_copy_is_not_double_counted():
    start_ms = 1_788_422_400_000
    payload = recovered_bar_payload(start_ms)
    calls: list[int] = []

    def recover(_symbol: str, _timeframe: str, requested_start: int, **_kwargs):
        calls.append(requested_start)
        return payload

    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="4h",
        first_expected_start_ms=start_ms,
        recovery_loader=recover,
        grace_ms=5_000,
    )
    boundary_ms = start_ms + timeframe_milliseconds("4h")

    assert tracker.recover_due(boundary_ms + 4_999) == ()
    assert tracker.recover_due(boundary_ms + 5_000) == (payload,)
    assert tracker.recover_due(boundary_ms + 10_000) == ()
    assert calls == [start_ms]

    tracker.observe(MarketStream.normalize(payload))
    late_ws_payload = dict(payload)
    late_ws_payload.pop("recovered")
    tracker.observe(MarketStream.normalize(late_ws_payload))

    snapshot = tracker.snapshot
    assert snapshot.expected_closed_bars == 1
    assert snapshot.rest_recovered_bars == 1
    assert snapshot.ws_closed_bars == 0
    assert snapshot.missing_closed_bars == 0
    assert snapshot.last_closed_bar_ms == boundary_ms - 1
    assert snapshot.last_expected_close_ms == boundary_ms - 1
    assert snapshot.data_healthy is True


def test_websocket_bar_received_before_grace_prevents_rest_recovery():
    start_ms = 1_788_422_400_000
    ws_payload = recovered_bar_payload(start_ms)
    ws_payload.pop("recovered")
    calls: list[int] = []
    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="4h",
        first_expected_start_ms=start_ms,
        recovery_loader=lambda *_args, **_kwargs: calls.append(start_ms),
        grace_ms=5_000,
    )
    tracker.observe(MarketStream.normalize(ws_payload))

    assert tracker.recover_due(start_ms + timeframe_milliseconds("4h") + 5_000) == ()
    assert calls == []
    assert tracker.snapshot.ws_closed_bars == 1
    assert tracker.snapshot.rest_recovered_bars == 0
    assert tracker.snapshot.data_healthy is True


def test_failed_recovery_marks_data_unhealthy_and_is_retry_bounded():
    start_ms = 1_788_422_400_000
    calls: list[int] = []

    def fail(_symbol: str, _timeframe: str, requested_start: int, **_kwargs):
        calls.append(requested_start)
        raise RuntimeError("offline")

    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="4h",
        first_expected_start_ms=start_ms,
        recovery_loader=fail,
        grace_ms=5_000,
        retry_interval_ms=30_000,
    )
    due_ms = start_ms + timeframe_milliseconds("4h") + 5_000

    assert tracker.recover_due(due_ms) == ()
    assert tracker.recover_due(due_ms + 29_999) == ()
    assert calls == [start_ms]
    snapshot = tracker.snapshot
    assert snapshot.expected_closed_bars == 1
    assert snapshot.missing_closed_bars == 1
    assert snapshot.recovery_failures == 1
    assert snapshot.data_healthy is False
    assert "offline" in (snapshot.last_recovery_error or "")

    assert tracker.recover_due(due_ms + 30_000) == ()
    assert calls == [start_ms, start_ms]
    assert tracker.snapshot.recovery_failures == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"instruments": (), "timeframe": "1m", "first_expected_start_ms": 0},
        {"instruments": ("ETHUSDT", "ethusdt"), "timeframe": "1m", "first_expected_start_ms": 0},
        {"instruments": ("ETHUSDT",), "timeframe": "1m", "first_expected_start_ms": -1},
        {"instruments": ("ETHUSDT",), "timeframe": "1m", "first_expected_start_ms": 1},
        {"instruments": ("ETHUSDT",), "timeframe": "1m", "first_expected_start_ms": 0, "grace_ms": -1},
        {"instruments": ("ETHUSDT",), "timeframe": "1m", "first_expected_start_ms": 0, "retry_interval_ms": 0},
    ],
)
def test_tracker_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        ClosedBarCompletenessTracker(**kwargs)


def test_tracker_ignores_irrelevant_events_and_rejects_corrupt_bar_identity():
    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="1m",
        first_expected_start_ms=0,
    )
    tick = MarketStream.normalize(
        {
            "event_id": "tick-1",
            "venue": "BINANCE",
            "instrument": "ETHUSDT",
            "timestamp_ms": 1,
            "bid": 1,
            "ask": 2,
            "bid_size": 1,
            "ask_size": 1,
            "last": 1.5,
            "last_size": 0,
        }
    )
    tracker.observe(tick)
    assert tracker.snapshot.ws_closed_bars == 0

    other_venue = recovered_bar_payload(0, "1m")
    other_venue["venue"] = "OTHER"
    tracker.observe(MarketStream.normalize(other_venue))
    assert tracker.snapshot.ws_closed_bars == 0

    missing_identity = recovered_bar_payload(0, "1m")
    missing_identity.pop("source_kline_start_ms")
    with pytest.raises(ValueError, match="missing source kline identity"):
        tracker.observe(MarketStream.normalize(missing_identity))

    wrong_id = recovered_bar_payload(0, "1m")
    wrong_id["event_id"] = "wrong"
    with pytest.raises(ValueError, match="event identity"):
        tracker.observe(MarketStream.normalize(wrong_id))

    wrong_close = recovered_bar_payload(0, "1m")
    wrong_close["source_kline_close_ms"] = 60_000
    with pytest.raises(ValueError, match="close boundary"):
        tracker.observe(MarketStream.normalize(wrong_close))


def test_tracker_recovery_rejects_wrong_or_non_recovered_payload_and_negative_clock():
    with pytest.raises(ValueError, match="observed_ms cannot be negative"):
        ClosedBarCompletenessTracker(
            instruments=("ETHUSDT",),
            timeframe="1m",
            first_expected_start_ms=0,
        ).recover_due(-1)

    wrong = recovered_bar_payload(60_000, "1m")
    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="1m",
        first_expected_start_ms=0,
        recovery_loader=lambda *_args, **_kwargs: wrong,
        grace_ms=0,
    )
    assert tracker.recover_due(60_000) == ()
    assert tracker.snapshot.recovery_failures == 1
    assert "wrong closed candle identity" in (tracker.snapshot.last_recovery_error or "")

    not_recovered = recovered_bar_payload(0, "1m")
    not_recovered.pop("recovered")
    tracker = ClosedBarCompletenessTracker(
        instruments=("ETHUSDT",),
        timeframe="1m",
        first_expected_start_ms=0,
        recovery_loader=lambda *_args, **_kwargs: not_recovered,
        grace_ms=0,
    )
    assert tracker.recover_due(60_000) == ()
    assert tracker.snapshot.recovery_failures == 1
    assert "authoritative recovered bar" in (tracker.snapshot.last_recovery_error or "")
