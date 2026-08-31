from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_strategy import compile_hft_genome_to_nautilus
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def test_order_book_hft_runs_real_nautilus_l2_entry_and_exit_lifecycle() -> None:
    from nautilus_trader.analysis.reporter import ReportProvider
    from nautilus_trader.backtest.config import BacktestEngineConfig
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.model.enums import AccountType, BookType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from nautilus_trader.test_kit.stubs.data import TestDataStubs

    instrument = TestInstrumentProvider.btcusdt_binance()
    genome = StrategyGenome(
        strategy_id="hft-l2-nautilus-1",
        family="order_book",
        style="order_book",
        instruments=(instrument.id.value,),
        timeframe="tick",
        entry={"type": "order_book_imbalance", "levels": 1, "threshold": 0.20},
        exit={"type": "imbalance_reversal_or_ticks", "ticks": 4},
        data_requirements=("L2",),
        allow_short=True,
    )
    strategy = compile_hft_genome_to_nautilus(
        genome,
        instruments={instrument.id.value: instrument},
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    base_ns = 1_700_000_000_000_000_000
    data = [
        TestDataStubs.order_book_snapshot(
            instrument=instrument,
            bid_price=100.0,
            ask_price=100.1,
            bid_size=100.0,
            ask_size=10.0,
            bid_levels=1,
            ask_levels=1,
            ts_event=base_ns,
            ts_init=base_ns,
        ),
        TestDataStubs.order_book_snapshot(
            instrument=instrument,
            bid_price=100.0,
            ask_price=100.1,
            bid_size=10.0,
            ask_size=100.0,
            bid_levels=1,
            ask_levels=1,
            ts_event=base_ns + 1_000_000,
            ts_init=base_ns + 1_000_000,
        ),
    ]

    engine = BacktestEngine(config=BacktestEngineConfig())
    engine.add_venue(
        venue=Venue("BINANCE"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money.from_str("10 BTC"), Money.from_str("100000 USDT")],
        book_type=BookType.L2_MBP,
    )
    engine.add_instrument(instrument)
    engine.add_data(data)
    engine.add_strategy(strategy)

    try:
        engine.run()
        orders = engine.cache.orders()
        orders_report = ReportProvider.generate_orders_report(orders)
        fills_report = ReportProvider.generate_fills_report(orders)

        assert len(orders_report.index) >= 2
        assert len(fills_report.index) >= 2
        assert strategy.last_exit_reason == "hft_imbalance_reversal"
        assert engine.portfolio.is_flat(instrument.id)
    finally:
        engine.dispose()


def test_scalping_hft_runs_real_nautilus_tick_entry_and_target_exit_lifecycle() -> None:
    from nautilus_trader.analysis.reporter import ReportProvider
    from nautilus_trader.backtest.config import BacktestEngineConfig
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from nautilus_trader.test_kit.stubs.data import TestDataStubs

    instrument = TestInstrumentProvider.btcusdt_binance()
    genome = StrategyGenome(
        strategy_id="hft-tick-nautilus-1",
        family="scalping",
        style="scalping",
        instruments=(instrument.id.value,),
        timeframe="tick",
        entry={"type": "micro_momentum", "ticks": 1},
        exit={"type": "ticks_or_timeout", "stop_ticks": 3, "target_ticks": 2, "max_ticks": 20},
        filters={"spread_max_ticks": 2},
        data_requirements=("TICK",),
        allow_short=True,
    )
    strategy = compile_hft_genome_to_nautilus(
        genome,
        instruments={instrument.id.value: instrument},
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )

    base_ns = 1_700_000_000_000_000_000
    data = [
        TestDataStubs.quote_tick(
            instrument=instrument,
            bid_price=100.00,
            ask_price=100.01,
            bid_size=10.0,
            ask_size=10.0,
            ts_event=base_ns,
            ts_init=base_ns,
        ),
        TestDataStubs.quote_tick(
            instrument=instrument,
            bid_price=100.01,
            ask_price=100.02,
            bid_size=10.0,
            ask_size=10.0,
            ts_event=base_ns + 1_000_000,
            ts_init=base_ns + 1_000_000,
        ),
        TestDataStubs.quote_tick(
            instrument=instrument,
            bid_price=100.06,
            ask_price=100.07,
            bid_size=10.0,
            ask_size=10.0,
            ts_event=base_ns + 2_000_000,
            ts_init=base_ns + 2_000_000,
        ),
    ]

    engine = BacktestEngine(config=BacktestEngineConfig())
    engine.add_venue(
        venue=Venue("BINANCE"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money.from_str("10 BTC"), Money.from_str("100000 USDT")],
    )
    engine.add_instrument(instrument)
    engine.add_data(data)
    engine.add_strategy(strategy)

    try:
        engine.run()
        orders = engine.cache.orders()
        orders_report = ReportProvider.generate_orders_report(orders)
        fills_report = ReportProvider.generate_fills_report(orders)

        assert len(orders_report.index) >= 2
        assert len(fills_report.index) >= 2
        assert strategy.last_exit_reason == "hft_target_ticks"
        assert engine.portfolio.is_flat(instrument.id)
    finally:
        engine.dispose()
