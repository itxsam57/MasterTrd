import pytest

from mastertrd.bar_completeness import (
    canonical_binance_kline_event_id,
    expected_closed_start_ms,
    timeframe_milliseconds,
)


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
