from datetime import timezone

import pytest

from mastertrd.data.binance_public import binance_kline_url, parse_kline_row


def test_monthly_spot_url_is_deterministic_and_public():
    assert binance_kline_url(
        market="spot",
        symbol="BTCUSDT",
        interval="1h",
        period="2026-07",
    ) == "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2026-07.zip"


def test_parse_kline_row_maps_to_canonical_market_bar():
    row = [
        "1722470400000", "64000.0", "65000.0", "63500.0", "64800.0", "123.4",
        "1722473999999", "0", "10", "0", "0", "0",
    ]
    bar = parse_kline_row(row, symbol="BTCUSDT", interval="1h", venue="BINANCE")
    assert bar.timestamp.tzinfo is timezone.utc
    assert bar.instrument == "BTCUSDT"
    assert bar.open == 64000.0
    assert bar.high == 65000.0
    assert bar.low == 63500.0
    assert bar.close == 64800.0
    assert bar.volume == 123.4


def test_parser_accepts_microsecond_epoch_used_by_newer_public_data():
    row = [
        "1722470400000000", "1", "2", "0.5", "1.5", "3",
        "1722473999999999", "0", "1", "0", "0", "0",
    ]
    bar = parse_kline_row(row, symbol="ETHUSDT", interval="15m")
    assert bar.timestamp.year == 2024


def test_url_rejects_path_injection_and_unknown_market():
    with pytest.raises(ValueError):
        binance_kline_url(market="spot", symbol="../BTC", interval="1h", period="2026-07")
    with pytest.raises(ValueError):
        binance_kline_url(market="options", symbol="BTCUSDT", interval="1h", period="2026-07")
