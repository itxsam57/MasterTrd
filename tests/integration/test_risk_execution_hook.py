from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_backtest import run_binance_spot_strategy_history
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.risk import RiskAction
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def test_compiled_strategy_records_risk_allow_before_every_simulated_order():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="risk-hook-ema-1",
        family="trend",
        style="day",
        instruments=(instrument.id.value,),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8},
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )
    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size="0.10000",
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    bar_type = strategy.config.bar_type
    prices = [2100 - i * 2 for i in range(15)] + [2070 + i * 5 for i in range(20)] + [2165 - i * 6 for i in range(20)]
    base_ns = 1_700_000_000_000_000_000
    bars = []
    previous = prices[0] + 1
    for index, close in enumerate(prices):
        open_value = float(previous)
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
        previous = close

    summary = run_binance_spot_strategy_history(
        instrument=instrument,
        data=bars,
        strategy=strategy,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert summary.order_count >= 1
    assert strategy.risk_runtime.decisions
    assert strategy.risk_runtime.allow_count >= summary.order_count
    assert all(decision.action is RiskAction.ALLOW for decision in strategy.risk_runtime.accepted_decisions)
    assert strategy.risk_runtime.accepted_order_fingerprints
