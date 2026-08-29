from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar, StrategyState
from mastertrd.memory_duckdb import DuckDbResearchMemory
from mastertrd.nautilus_data import market_bars_to_nautilus
from mastertrd.research.generator import generate_candidate
from mastertrd.research_cycle import run_generated_backtest_cycle


def test_generated_backtest_cycle_evaluates_promotes_and_persists(tmp_path):
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = generate_candidate(
        family="trend",
        instruments=(instrument.id.value,),
        seed=42,
    )
    unit = candidate.timeframe[-1]
    amount = int(candidate.timeframe[:-1])
    step = timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount)
    closes = (
        [2300.0 - i * 2.0 for i in range(100)]
        + [2100.0 + i * 4.0 for i in range(100)]
        + [2496.0 - i * 5.0 for i in range(100)]
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market_bars = []
    previous = closes[0] + 1.0
    for index, close in enumerate(closes):
        market_bars.append(
            MarketBar(
                venue="BINANCE",
                instrument="ETHUSDT",
                timeframe=candidate.timeframe,
                timestamp=start + step * index,
                open=previous,
                high=max(previous, close) + 1.0,
                low=min(previous, close) - 1.0,
                close=close,
                volume=1.0,
            )
        )
        previous = close

    bars = market_bars_to_nautilus(market_bars, instrument=instrument)
    memory = DuckDbResearchMemory(tmp_path / "research.duckdb")
    cycle = run_generated_backtest_cycle(
        experiment_id="generated-cycle-001",
        candidate=candidate,
        instrument=instrument,
        data=bars,
        dataset_hash="generated-cycle-data-v1",
        code_hash="generated-cycle-code-v1",
        trade_size="0.01000",
        memory=memory,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert cycle.result.trade_count >= 1
    assert cycle.evidence.evidence_type == "nautilus_backtest"
    assert cycle.evidence.passed is True
    assert cycle.promotion.allowed is True
    assert cycle.promotion.target is StrategyState.BACKTESTED
    assert cycle.record.experiment_id == "generated-cycle-001"
    assert cycle.record.genome_hash == candidate.genome_hash
    assert cycle.record.status == "BACKTESTED"
    assert cycle.record.engine == "nautilus_trader"
    assert cycle.record.metadata["evidence_hash"] == cycle.evidence.evidence_hash
    assert cycle.record.metadata["dataset_hash"] == "generated-cycle-data-v1"
    assert memory.count() == 1

    memory.close()
    reopened = DuckDbResearchMemory(tmp_path / "research.duckdb")
    assert reopened.get("generated-cycle-001") == cycle.record
    reopened.close()
