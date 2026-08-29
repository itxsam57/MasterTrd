from mastertrd.data.binance_public import parse_kline_row
from mastertrd.nautilus_backtest import run_binance_spot_history
from mastertrd.nautilus_data import market_bars_to_nautilus


def test_binance_market_bars_convert_to_real_nautilus_bars_and_replay():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    rows = (
        (1700000000000, "2000.00", "2005.00", "1995.00", "2001.00", "1.123456789"),
        (1700000060000, "2001.00", "2010.00", "1999.00", "2008.00", "2.987654321"),
        (1700000120000, "2008.00", "2012.00", "2002.00", "2004.00", "3.500000000"),
    )
    market_bars = tuple(
        parse_kline_row(row, symbol="ETHUSDT", interval="1m")
        for row in rows
    )

    bars = market_bars_to_nautilus(market_bars, instrument=instrument)

    assert len(bars) == 3
    assert all(isinstance(bar, Bar) for bar in bars)
    assert bars[0].bar_type.instrument_id == instrument.id
    assert str(bars[0].bar_type).endswith("1-MINUTE-LAST-EXTERNAL")
    assert float(bars[0].open) == 2000.0
    assert float(bars[0].high) == 2005.0
    assert float(bars[0].low) == 1995.0
    assert float(bars[0].close) == 2001.0
    assert float(bars[0].volume) > 0.0
    assert bars[0].ts_event == 1_700_000_000_000_000_000
    assert bars[1].ts_event - bars[0].ts_event == 60_000_000_000

    summary = run_binance_spot_history(
        instrument=instrument,
        data=bars,
        starting_balances=("10 ETH", "100000 USDT"),
    )
    assert summary.engine == "nautilus_trader"
    assert summary.event_count == 3
    assert summary.iterations > 0


def test_bridge_rejects_wrong_instrument_venue_and_mixed_timeframes():
    import pytest
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    valid = parse_kline_row(
        (1700000000000, "2000", "2005", "1995", "2001", "1"),
        symbol="ETHUSDT",
        interval="1m",
    )
    wrong_symbol = parse_kline_row(
        (1700000060000, "2001", "2006", "1999", "2002", "1"),
        symbol="BTCUSDT",
        interval="1m",
    )
    wrong_venue = parse_kline_row(
        (1700000060000, "2001", "2006", "1999", "2002", "1"),
        symbol="ETHUSDT",
        interval="1m",
        venue="OTHER",
    )
    other_timeframe = parse_kline_row(
        (1700000060000, "2001", "2006", "1999", "2002", "1"),
        symbol="ETHUSDT",
        interval="5m",
    )

    with pytest.raises(ValueError, match="instrument"):
        market_bars_to_nautilus((valid, wrong_symbol), instrument=instrument)
    with pytest.raises(ValueError, match="venue"):
        market_bars_to_nautilus((valid, wrong_venue), instrument=instrument)
    with pytest.raises(ValueError, match="timeframe"):
        market_bars_to_nautilus((valid, other_timeframe), instrument=instrument)
