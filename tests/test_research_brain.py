from mastertrd.memory_duckdb import DuckDbResearchMemory
from mastertrd.research_brain import RESEARCH_STAGES, ResearchBrainConfig


def test_research_brain_config_and_stage_receipts_are_deterministic(tmp_path):
    config = ResearchBrainConfig(
        families=("trend",),
        instruments=("ETHUSDT.BINANCE",),
        seed_start=42,
        seed_stop=43,
        screening_min_return=-1.0,
        optimization_trials=2,
        evolution_generations=1,
        evolution_population=4,
        validation_budget=1,
        paper_queue_cap=1,
    )
    assert config.seed_count == 1
    assert len(RESEARCH_STAGES) == 13
    assert RESEARCH_STAGES[0] == "verified_data"
    assert RESEARCH_STAGES[-1] == "champion_challenger_rerank"

    memory = DuckDbResearchMemory(tmp_path / "brain.duckdb")
    receipt = memory.record_stage(
        run_id="run-001",
        stage=RESEARCH_STAGES[0],
        artifact={"dataset_hash": "d" * 64, "verified": True},
    )
    duplicate = memory.record_stage(
        run_id="run-001",
        stage=RESEARCH_STAGES[0],
        artifact={"dataset_hash": "d" * 64, "verified": True},
    )

    assert duplicate == receipt
    assert memory.get_stage("run-001", RESEARCH_STAGES[0]) == receipt
    assert memory.stage_receipts("run-001") == [receipt]
    memory.close()
