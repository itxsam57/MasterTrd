from mastertrd.nautilus_backtest import run_binance_spot_history


def test_stable_nautilus_replays_local_binance_history():
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide
    from nautilus_trader.model.identifiers import TradeId
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    base_ns = 1_700_000_000_000_000_000
    trades = [
        TradeTick(
            instrument_id=instrument.id,
            price=Price.from_str(f"{2000 + index * 0.01:.2f}"),
            size=Quantity.from_str("0.01000"),
            aggressor_side=AggressorSide.BUYER if index % 2 == 0 else AggressorSide.SELLER,
            trade_id=TradeId(str(index + 1)),
            ts_event=base_ns + index * 1_000_000_000,
            ts_init=base_ns + index * 1_000_000_000,
        )
        for index in range(500)
    ]

    summary = run_binance_spot_history(
        instrument=instrument,
        data=trades,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert summary.engine == "nautilus_trader"
    assert summary.event_count == 500
    assert summary.iterations > 0
    assert summary.instrument_id == instrument.id.value
