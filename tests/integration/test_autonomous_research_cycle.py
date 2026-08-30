from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar, StrategyState
from mastertrd.memory_duckdb import DuckDbResearchMemory
from mastertrd.research_brain import ResearchBrainConfig, ResearchDataset, run_research_brain


def _step(timeframe: str) -> timedelta:
    amount = int(timeframe[:-1])
    return timedelta(minutes=amount) if timeframe.endswith("m") else timedelta(hours=amount)


def _market_series(instrument, *, timeframe: str, count: int, start: datetime, offset: float):
    cycle = (
        [2300.0 + offset - index * 2.0 for index in range(100)]
        + [2100.0 + offset + index * 4.0 for index in range(100)]
        + [2496.0 + offset - index * 5.0 for index in range(100)]
    )
    closes = [cycle[index % len(cycle)] for index in range(count)]
    step = _step(timeframe)
    bars = []
    previous = closes[0] + 1.0
    for index, close in enumerate(closes):
        bars.append(
            MarketBar(
                venue=str(instrument.id.venue),
                instrument=str(instrument.raw_symbol),
                timeframe=timeframe,
                timestamp=start + step * index,
                open=previous,
                high=max(previous, close) + 1.0,
                low=min(previous, close) - 1.0,
                close=close,
                volume=1.0,
            )
        )
        previous = close
    return tuple(bars)


def test_research_brain_runs_all_stages_stores_every_outcome_and_resumes(tmp_path):
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    eth = TestInstrumentProvider.ethusdt_binance()
    btc = TestInstrumentProvider.btcusdt_binance()
    # Seed 42 is intentionally used because the generated trend family has a
    # deterministic, active EMA strategy already proven by the execution tests.
    config = ResearchBrainConfig(
        families=("trend",),
        instruments=(eth.id.value,),
        seed_start=42,
        seed_stop=43,
        screening_min_return=-1.0,
        optimization_trials=2,
        evolution_generations=1,
        evolution_population=4,
        validation_budget=1,
        paper_queue_cap=1,
        hidden_fraction=0.20,
        trade_size="0.01000",
        starting_balances=("10 ETH", "10 BTC", "100000 USDT"),
    )
    timeframe = "4h"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dataset = ResearchDataset(
        dataset_hash="brain-source-v1",
        bars_by_instrument={
            eth.id.value: _market_series(eth, timeframe=timeframe, count=1500, start=start, offset=0.0),
            btc.id.value: _market_series(btc, timeframe=timeframe, count=1500, start=start, offset=50.0),
        },
        nautilus_instruments={eth.id.value: eth, btc.id.value: btc},
    )
    memory = DuckDbResearchMemory(tmp_path / "research.duckdb")

    report = run_research_brain(
        config,
        dataset,
        memory,
        code_hash="c" * 64,
        lock_hash="l" * 64,
    )

    assert report.generated == 1
    assert report.stored == report.generated
    assert len(report.stage_receipts) == 13
    assert report.stage_receipts[-1].stage == "champion_challenger_rerank"
    assert report.paper_queued == 1
    assert len(report.finalists) == 1
    assert report.finalists[0].state is StrategyState.PAPER
    assert memory.count() == 1

    repeated = run_research_brain(
        config,
        dataset,
        memory,
        code_hash="c" * 64,
        lock_hash="l" * 64,
    )
    assert repeated.run_id == report.run_id
    assert repeated.resumed is True
    assert repeated.finalists == report.finalists
    assert memory.count() == 1
    assert len(memory.stage_receipts(report.run_id)) == 13
    memory.close()
