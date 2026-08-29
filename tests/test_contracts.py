from datetime import datetime, timezone
import pytest

from mastertrd.contracts import MarketBar


def test_market_bar_accepts_consistent_ohlc():
    bar = MarketBar(datetime.now(timezone.utc), "BINANCE", "BTCUSDT", "1h", 100, 110, 90, 105, 12)
    assert bar.close == 105


def test_market_bar_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketBar(datetime.now(), "BINANCE", "BTCUSDT", "1h", 100, 110, 90, 105, 12)


def test_market_bar_rejects_inconsistent_high():
    with pytest.raises(ValueError, match="high"):
        MarketBar(datetime.now(timezone.utc), "BINANCE", "BTCUSDT", "1h", 100, 101, 90, 105, 12)
