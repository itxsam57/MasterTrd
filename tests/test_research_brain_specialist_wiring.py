from types import SimpleNamespace

import mastertrd.research_brain as research_brain
from mastertrd.research.generator import generate_candidate
from mastertrd.specialist_orchestrator import SpecialistInputs


class _Memory:
    def get_stage(self, run_id, stage):
        del run_id, stage
        return None

    def stage_receipts(self, run_id):
        del run_id
        return []


def _config():
    return research_brain.ResearchBrainConfig(
        families=("stat_arb",),
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed_start=1,
        seed_stop=2,
        screening_min_return=-1.0,
        optimization_trials=1,
        evolution_generations=1,
        evolution_population=2,
        validation_budget=1,
        paper_queue_cap=0,
        validation_window=50,
    )


def test_run_research_brain_routes_candidate_bound_inputs_into_durable_specialist_stage(monkeypatch):
    candidate = generate_candidate(
        family="stat_arb",
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed=7,
    )
    validation_item = {
        "genome": candidate.canonical_payload(),
        "passed": True,
        "score": 0.25,
        "reason": "validated promotion evidence satisfied",
    }
    supplied = SpecialistInputs()
    seen = {}

    def fake_specialist_stage(validated_outcomes, *, specialist_inputs_by_genome_hash):
        seen["validated_outcomes"] = tuple(validated_outcomes)
        seen["inputs"] = specialist_inputs_by_genome_hash
        return {"outcomes": []}

    artifacts = {
        "verified_data": {"configured_present": True},
        "load_memory": {"records_before": 0},
        "regime_discovery": {"regimes": {}},
        "generation_mutation": {"genomes": [], "blockers": []},
        "vectorbt_screen": {"outcomes": []},
        "optuna_tune": {"outcomes": []},
        "pymoo_evolution": {"outcomes": []},
        "nautilus_validation": {"outcomes": [validation_item]},
        "hidden_robustness_stress": {"outcomes": []},
        "store_outcomes": {"stored_ids": [], "stored": 0},
        "queue_paper": {"paper_queued": 0, "finalists": []},
        "champion_challenger_rerank": {
            "generated": 0,
            "stored": 0,
            "paper_queued": 0,
            "finalists": [],
        },
    }

    def fake_stage(memory, run_id, name, produce):
        del memory, run_id
        if name == "specialist_tests":
            return dict(produce()), False
        return artifacts[name], False

    monkeypatch.setattr(research_brain, "_stage", fake_stage)
    monkeypatch.setattr(research_brain, "run_research_specialist_stage", fake_specialist_stage)

    research_brain.run_research_brain(
        _config(),
        SimpleNamespace(dataset_hash="dataset-v1"),
        _Memory(),
        code_hash="code-v1",
        lock_hash="lock-v1",
        specialist_inputs_by_genome_hash={candidate.genome_hash: supplied},
    )

    assert seen["validated_outcomes"] == (validation_item,)
    assert seen["inputs"] == {candidate.genome_hash: supplied}
