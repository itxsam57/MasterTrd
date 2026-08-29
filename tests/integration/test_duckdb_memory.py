import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.memory_duckdb import DuckDbResearchMemory


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-DURABLE-MEM",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="15m",
        entry={"kind": "ema_cross", "fast_period": 8, "slow_period": 32, "trade_size": "0.01"},
        exit={"kind": "cross_reverse"},
    )


def test_duckdb_memory_is_idempotent_queryable_and_exports_parquet(tmp_path):
    path = tmp_path / "research.duckdb"
    memory = DuckDbResearchMemory(path)
    candidate = genome()

    first = memory.append(
        experiment_id="exp-001",
        genome=candidate,
        status="BACKTESTED",
        engine="nautilus_trader",
        score=0.73,
        reason="baseline",
        metadata={"dataset_hash": "dataset-a", "trade_count": 42},
    )
    duplicate = memory.append(
        experiment_id="exp-001",
        genome=candidate,
        status="BACKTESTED",
        engine="nautilus_trader",
        score=0.73,
        reason="baseline",
        metadata={"dataset_hash": "dataset-a", "trade_count": 42},
    )

    assert duplicate == first
    assert memory.count() == 1
    assert memory.get("exp-001") == first
    assert memory.by_genome(candidate.genome_hash) == [first]
    assert memory.by_status("BACKTESTED") == [first]

    memory.close()
    reopened = DuckDbResearchMemory(path)
    assert reopened.get("exp-001") == first

    parquet_path = tmp_path / "research.parquet"
    reopened.export_parquet(parquet_path)
    assert parquet_path.exists()

    import duckdb

    row = duckdb.connect().execute(
        "SELECT experiment_id, genome_hash, status, engine, score FROM read_parquet(?)",
        [str(parquet_path)],
    ).fetchone()
    assert row == (
        "exp-001",
        candidate.genome_hash,
        "BACKTESTED",
        "nautilus_trader",
        0.73,
    )
    reopened.close()


def test_duplicate_experiment_id_cannot_be_reused_for_different_result(tmp_path):
    memory = DuckDbResearchMemory(tmp_path / "research.duckdb")
    candidate = genome()
    memory.append(
        experiment_id="exp-fixed",
        genome=candidate,
        status="SCREENED",
        engine="vectorbt",
        score=0.4,
    )

    with pytest.raises(ValueError, match="experiment_id"):
        memory.append(
            experiment_id="exp-fixed",
            genome=candidate,
            status="BACKTESTED",
            engine="nautilus_trader",
            score=0.8,
        )
    assert memory.count() == 1
    memory.close()


def test_invalid_identity_and_nonfinite_scores_are_rejected(tmp_path):
    memory = DuckDbResearchMemory(tmp_path / "research.duckdb")
    with pytest.raises(ValueError, match="experiment_id"):
        memory.append(
            experiment_id="",
            genome=genome(),
            status="SCREENED",
            engine="vectorbt",
            score=0.5,
        )
    with pytest.raises(ValueError, match="finite"):
        memory.append(
            experiment_id="exp-nan",
            genome=genome(),
            status="SCREENED",
            engine="vectorbt",
            score=float("nan"),
        )
    memory.close()
