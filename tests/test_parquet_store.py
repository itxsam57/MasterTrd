from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mastertrd.contracts import MarketBar
from mastertrd.data.parquet_store import read_market_bars, write_market_bars


def _bars() -> tuple[MarketBar, MarketBar]:
    first = MarketBar(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        venue="BINANCE",
        instrument="BTCUSDT",
        timeframe="1m",
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=10.0,
        extras={"trade_count": 12},
    )
    second = MarketBar(
        timestamp=first.timestamp + timedelta(minutes=1),
        venue="BINANCE",
        instrument="BTCUSDT",
        timeframe="1m",
        open=101.0,
        high=103.0,
        low=100.0,
        close=102.0,
        volume=11.0,
        extras={"trade_count": 13},
    )
    return first, second


def test_parquet_roundtrip_preserves_market_bars(tmp_path) -> None:
    path = tmp_path / "nested" / "bars.parquet"
    source = _bars()

    manifest = write_market_bars(path, source)
    restored = read_market_bars(path)

    assert restored == source
    assert manifest.path == path
    assert manifest.row_count == 2
    assert manifest.instrument == "BTCUSDT"
    assert len(manifest.dataset_hash) == 64
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_parquet_writer_rejects_mixed_instruments(tmp_path) -> None:
    first, second = _bars()
    second = MarketBar(
        timestamp=second.timestamp,
        venue=second.venue,
        instrument="ETHUSDT",
        timeframe=second.timeframe,
        open=second.open,
        high=second.high,
        low=second.low,
        close=second.close,
        volume=second.volume,
    )

    with pytest.raises(ValueError, match="single instrument"):
        write_market_bars(tmp_path / "bars.parquet", (first, second))
