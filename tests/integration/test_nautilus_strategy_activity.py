from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_backtest import run_binance_spot_strategy_history
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def _bars_for_prices(bar_type, prices):
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity

    base_ns = 1_700_000_000_000_000_000
    bars = []
    previous_close = prices[0] + 1
    for index, close in enumerate(prices):
        open_value = float(previous_close)
        close_value = float(close)
        high_value = max(open_value, close_value) + 1.0
        low_value = min(open_value, close_value) - 1.0
        bars.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{open_value:.2f}"),
                high=Price.from_str(f"{high_value:.2f}"),
                low=Price.from_str(f"{low_value:.2f}"),
                close=Price.from_str(f"{close_value:.2f}"),
                volume=Quantity.from_str("1.00000"),
                ts_event=base_ns + index * 60_000_000_000,
                ts_init=base_ns + index * 60_000_000_000,
            )
        )
        previous_close = close
    return bars


def test_compiled_genome_generates_real_simulated_orders_and_fills():
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
    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    bars = _bars_for_prices(
        strategy.config.bar_type,
        [2100 - i * 2 for i in range(15)]
        + [2070 + i * 5 for i in range(20)]
        + [2165 - i * 6 for i in range(20)],
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


def test_generated_bar_strategy_executes_atr_target_in_nautilus() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="atr-exit-activity-1",
        family="momentum",
        style="intraday",
        instruments=(instrument.id.value,),
        timeframe="1m",
        entry={
            "type": "rsi_momentum",
            "period": 3,
            "threshold": 55,
            "trade_size": "0.10",
        },
        exit={
            "type": "atr_bracket",
            "stop_atr": 3.0,
            "target_atr": 1.0,
            "atr_period": 3,
        },
        allow_short=True,
    )
    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    bars = _bars_for_prices(
        strategy.config.bar_type,
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 112.0, 113.0, 114.0],
    )

    summary = run_binance_spot_strategy_history(
        instrument=instrument,
        data=bars,
        strategy=strategy,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert summary.order_count >= 2
    assert summary.fill_count >= 2
    assert strategy.last_exit_reason == "atr_target"
