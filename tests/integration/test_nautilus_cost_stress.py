from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_evaluation import run_binance_spot_evaluation
from mastertrd.nautilus_risk_hook import build_research_nautilus_risk_runtime


def _fixture():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="ema-cost-stress-1",
        family="trend",
        style="day",
        instruments=(instrument.id.value,),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )
    from mastertrd.nautilus_strategy import compile_genome_to_nautilus

    bar_type = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        risk_runtime=build_research_nautilus_risk_runtime(),
    ).config.bar_type
    prices = [2100 - i * 2 for i in range(15)] + [2070 + i * 5 for i in range(20)] + [2165 - i * 6 for i in range(20)]
    base_ns = 1_700_000_000_000_000_000
    bars = []
    previous_close = prices[0] + 1
    for index, close in enumerate(prices):
        open_value = float(previous_close)
        close_value = float(close)
        bars.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{open_value:.2f}"),
                high=Price.from_str(f"{max(open_value, close_value) + 1.0:.2f}"),
                low=Price.from_str(f"{min(open_value, close_value) - 1.0:.2f}"),
                close=Price.from_str(f"{close_value:.2f}"),
                volume=Quantity.from_str("1.00000"),
                ts_event=base_ns + index * 60_000_000_000,
                ts_init=base_ns + index * 60_000_000_000,
            )
        )
        previous_close = close
    return instrument, genome, bars


def test_higher_execution_costs_reduce_realized_backtest_return():
    instrument, genome, bars = _fixture()
    common = dict(
        genome=genome,
        instrument=instrument,
        data=bars,
        dataset_hash="cost-stress-dataset-v1",
        code_hash="cost-stress-code-v1",
        starting_balances=("10 ETH", "100000 USDT"),
    )
    base = run_binance_spot_evaluation(**common, fees=0.0, slippage=0.0)
    stressed = run_binance_spot_evaluation(**common, fees=0.001, slippage=0.001)

    assert base.trade_count >= 1
    assert stressed.trade_count == base.trade_count
    assert stressed.total_return < base.total_return
    assert stressed.expectancy < base.expectancy
