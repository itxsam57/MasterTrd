from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_backtest import run_binance_spot_strategy_history
from mastertrd.nautilus_strategy import compile_genome_to_nautilus


def test_compiled_genome_generates_real_simulated_orders_and_fills():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="ema-activity-1",
        family="trend",
        style="day",
        instruments=(instrument.id.value,),
        timeframe="1m",
        entry={
            "kind": "ema_cross",
            "fast_period": 3,
            "slow_period": 8,
            "trade_size": "0.10",
        },
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )
    strategy = compile_genome_to_nautilus(genome, instrument=instrument)
    bar_type = strategy.config.bar_type

    prices = (
        [2100 - i * 2 for i in range(15)]
        + [2070 + i * 5 for i in range(20)]
        + [2165 - i * 6 for i in range(20)]
    )
    base_ns = 1_700_000_000_000_000_000
    bars = []
    for index, close in enumerate(prices):
        value = Price.from_str(f"{close:.2f}")
        bars.append(
            Bar(
                bar_type=bar_type,
                open=value,
                high=value,
                low=value,
                close=value,
                volume=Quantity.from_str("1.00000"),
                ts_event=base_ns + index * 60_000_000_000,
                ts_init=base_ns + index * 60_000_000_000,
            )
        )

    summary = run_binance_spot_strategy_history(
        instrument=instrument,
        data=bars,
        strategy=strategy,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert summary.engine == "nautilus_trader"
    assert summary.event_count == len(bars)
    assert summary.order_count >= 1
    assert summary.fill_count >= 1
