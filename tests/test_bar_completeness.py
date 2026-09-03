import json

import pytest

from mastertrd.bar_completeness import (
    canonical_binance_kline_event_id,
    expected_closed_start_ms,
    load_public_binance_closed_kline,
    timeframe_milliseconds,
)


class FakeResponse:
    def __init__(self, payload: object):
        self._content = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


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
