from __future__ import annotations

from mastertrd.data.ccxt_fallback import fetch_ohlcv_fallback


class FakeExchange:
    def __init__(self) -> None:
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls.append((symbol, timeframe, since, limit))
        return [
            [1_700_000_000_000, 100, 101, 99, 100.5, 10],
            [1_700_000_060_000, 100.5, 102, 100, 101, 11],
        ]

    def create_order(self, *args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("data fallback attempted execution")


def test_ccxt_fallback_normalizes_ohlcv_without_execution() -> None:
    exchange = FakeExchange()

    bars = fetch_ohlcv_fallback(
        exchange,
        venue="BINANCE",
        symbol="BTC/USDT",
        instrument="BTCUSDT",
        timeframe="1m",
        since=1_700_000_000_000,
        limit=2,
    )

    assert len(bars) == 2
    assert bars[0].instrument == "BTCUSDT"
    assert bars[0].venue == "BINANCE"
    assert bars[0].timestamp < bars[1].timestamp
    assert exchange.calls == [("BTC/USDT", "1m", 1_700_000_000_000, 2)]
