from mastertrd.nautilus_backtest import run_binance_spot_history


def test_stable_nautilus_replays_bundled_binance_history():
    from nautilus_trader.persistence.wranglers import TradeTickDataWrangler
    from nautilus_trader.test_kit.providers import TestDataProvider, TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    raw = TestDataProvider().read_csv_ticks("binance/ethusdt-trades.csv")
    trades = TradeTickDataWrangler(instrument=instrument).process(raw)

    summary = run_binance_spot_history(
        instrument=instrument,
        data=trades[:500],
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert summary.engine == "nautilus_trader"
    assert summary.event_count == 500
    assert summary.iterations > 0
    assert summary.instrument_id == instrument.id.value
