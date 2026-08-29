from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_backtest import run_binance_spot_strategy_history
from mastertrd.nautilus_paper import probe_nautilus_sandbox_session
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.paper_events import NautilusPaperEventSink
from mastertrd.paper_session import PaperSessionJournal


def test_real_nautilus_position_closed_events_are_recorded_into_paper_journal():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="paper-event-sink-1",
        family="trend",
        style="day",
        instruments=(instrument.id.value,),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )
    compiled = compile_genome_to_nautilus(genome, instrument=instrument)
    base_ns = 1_700_000_000_000_000_000
    receipt = probe_nautilus_sandbox_session(genome, session_nonce="event-sink-session")
    journal = PaperSessionJournal(receipt, code_hash="code-event-sink-v1", started_ns=base_ns)
    sink = NautilusPaperEventSink(journal)

    strategy_type = type(compiled)

    class RecordingStrategy(strategy_type):
        def on_position_closed(self, event):
            sink.on_position_closed(event)
            parent = getattr(super(), "on_position_closed", None)
            if parent is not None:
                parent(event)

    strategy = RecordingStrategy(config=compiled.config)
    bar_type = strategy.config.bar_type
    prices = (
        [2100 - i * 2 for i in range(15)]
        + [2070 + i * 5 for i in range(20)]
        + [2165 - i * 6 for i in range(20)]
    )
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

    summary = run_binance_spot_strategy_history(
        instrument=instrument,
        data=bars,
        strategy=strategy,
        starting_balances=("10 ETH", "100000 USDT"),
    )
    assert summary.fill_count >= 1
    assert sink.closed_positions >= 1

    journal.record_reconciliation(
        "post-engine-reconciliation",
        ok=True,
        timestamp_ns=bars[-1].ts_event + 1,
    )
    report = journal.finalize(ended_ns=bars[-1].ts_event + 2)
    assert report.closed_trades == sink.closed_positions
    assert report.closed_trades >= 1
    assert report.provenance_verified is True
