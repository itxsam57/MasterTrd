from mastertrd.genome import StrategyGenome
from mastertrd.memory import JsonlResearchMemory


def genome():
    return StrategyGenome(
        strategy_id="S-MEM",
        family="mean_reversion",
        style="day",
        instruments=("BTCUSDT",),
        timeframe="15m",
        entry={"rsi_lt": 30},
        exit={"rsi_gt": 50},
    )


def test_memory_round_trip(tmp_path):
    memory = JsonlResearchMemory(tmp_path / "research.jsonl")
    original = memory.append(genome(), status="SCREENED", engine="vectorbt", score=0.72, metadata={"trial": 3})
    loaded = memory.read_all()
    assert loaded == [original]
    assert loaded[0].genome_hash == genome().genome_hash


def test_missing_memory_is_empty(tmp_path):
    assert JsonlResearchMemory(tmp_path / "missing.jsonl").read_all() == []
