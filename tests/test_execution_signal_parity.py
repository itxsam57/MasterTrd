from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from mastertrd.contracts import MarketBar
from mastertrd.execution_signals import atr, donchian_extrema, ema, rsi, zscore


def _bars(closes: list[float]) -> tuple[MarketBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    previous = closes[0]
    for index, close in enumerate(closes):
        bars.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                venue="BINANCE",
                instrument="ETHUSDT.BINANCE",
                timeframe="1m",
                open=previous,
                high=max(previous, close) + 0.75,
                low=min(previous, close) - 0.5,
                close=close,
                volume=100.0 + index,
            )
        )
        previous = close
    return tuple(bars)


def test_ema_matches_talib() -> None:
    import talib

    values = np.asarray([100.0, 101.0, 99.5, 102.0, 104.0, 103.0, 106.0, 108.0], dtype=float)
    expected = float(talib.EMA(values, timeperiod=4)[-1])
    assert ema(values, 4) == pytest.approx(expected, abs=1e-9)


def test_rsi_matches_talib() -> None:
    import talib

    values = np.asarray(
        [100.0, 101.0, 99.0, 102.0, 100.5, 103.0, 104.0, 102.0, 105.0, 107.0],
        dtype=float,
    )
    expected = float(talib.RSI(values, timeperiod=5)[-1])
    assert rsi(values, 5) == pytest.approx(expected, abs=1e-9)


def test_atr_matches_talib() -> None:
    import talib

    bars = _bars([100.0, 101.0, 99.5, 102.0, 104.0, 103.0, 106.0, 108.0, 107.0])
    highs = np.asarray([bar.high for bar in bars], dtype=float)
    lows = np.asarray([bar.low for bar in bars], dtype=float)
    closes = np.asarray([bar.close for bar in bars], dtype=float)
    expected = float(talib.ATR(highs, lows, closes, timeperiod=4)[-1])
    assert atr(bars, 4) == pytest.approx(expected, abs=1e-9)


def test_donchian_extrema_match_talib_max_min() -> None:
    import talib

    bars = _bars([100.0, 101.0, 99.5, 102.0, 104.0, 103.0, 106.0, 108.0])
    window = 4
    prior = bars[-window:]
    highs = np.asarray([bar.high for bar in prior], dtype=float)
    lows = np.asarray([bar.low for bar in prior], dtype=float)
    upper, lower = donchian_extrema(prior)
    assert upper == pytest.approx(float(talib.MAX(highs, timeperiod=window)[-1]), abs=1e-9)
    assert lower == pytest.approx(float(talib.MIN(lows, timeperiod=window)[-1]), abs=1e-9)


def test_zscore_matches_talib_sma_stddev() -> None:
    import talib

    history = np.asarray([100.0, 101.0, 99.5, 102.0, 104.0], dtype=float)
    current = 106.0
    mean = float(talib.SMA(history, timeperiod=len(history))[-1])
    deviation = float(talib.STDDEV(history, timeperiod=len(history), nbdev=1.0)[-1])
    expected = (current - mean) / deviation
    assert zscore(current, history) == pytest.approx(expected, abs=1e-9)
