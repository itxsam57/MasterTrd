from mastertrd.contracts import EvaluationResult
from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_evaluation import run_binance_spot_evaluation
from mastertrd.nautilus_risk_hook import build_research_nautilus_risk_runtime


def test_real_nautilus_backtest_maps_to_evaluation_result():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="ema-evaluation-1",
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

    from mastertrd.nautilus_strategy import compile_genome_to_nautilus

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        risk_runtime=build_research_nautilus_risk_runtime(),
    )
    bar_type = strategy.config.bar_type
    prices = (
        [2100 - i * 2 for i in range(15)]
        + [2070 + i * 5 for i in range(20)]
        + [2165 - i * 6 for i in range(20)]
    )
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

    dataset_hash = "d" * 64
    code_hash = "c" * 64
    result = run_binance_spot_evaluation(
        genome=genome,
        instrument=instrument,
        data=bars,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        fees=0.0,
        slippage=0.0,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert isinstance(result, EvaluationResult)
    assert result.strategy_id == genome.strategy_id
    assert result.genome_hash == genome.genome_hash
    assert result.dataset_hash == dataset_hash
    assert result.code_hash == code_hash
    assert result.engine == "nautilus_trader"
    assert result.engine_version == "1.231.0"
    assert result.trade_count >= 1
    assert result.max_drawdown >= 0.0
    assert result.fees == 0.0
    assert result.slippage == 0.0
