from dataclasses import asdict
from types import SimpleNamespace

import mastertrd.research_brain as research_brain
from mastertrd.research.generator import generate_candidate
from mastertrd.validation import ValidationEvidence


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


def test_research_brain_forwards_persisted_specialist_evidence_into_robustness(monkeypatch):
    candidate = generate_candidate(
        family="stat_arb",
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed=7,
    )
    evidence = ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="multi_leg_execution_stress",
        dataset_hash="specialist-dataset-v1",
        code_hash="code-v1",
        engine="nautilus_trader",
        engine_version="1.231.0",
        passed=True,
        metrics={"completed_cycles": 4.0},
    )
    specialist_item = {
        "genome": {**candidate.canonical_payload(), "genome_hash": candidate.genome_hash},
        "passed": True,
        "score": 0.25,
        "reason": "specialist_evidence_passed",
        "evidence": [asdict(evidence)],
        "missing_evidence": [],
        "failed_evidence": [],
    }

    points = tuple(SimpleNamespace(timestamp=index) for index in range(250))
    dataset = SimpleNamespace(
        dataset_hash="dataset-v1",
        bars_by_instrument={
            "BTCUSDT.BINANCE": points,
            "ETHUSDT.BINANCE": points,
        },
        nautilus_instruments={
            "BTCUSDT.BINANCE": object(),
            "ETHUSDT.BINANCE": object(),
        },
    )
    artifacts = {
        "verified_data": {"configured_present": True},
        "load_memory": {"records_before": 0},
        "regime_discovery": {"regimes": {}},
        "generation_mutation": {"genomes": [], "blockers": []},
        "vectorbt_screen": {"outcomes": []},
        "optuna_tune": {"outcomes": []},
        "pymoo_evolution": {"outcomes": []},
        "nautilus_validation": {"outcomes": []},
        "specialist_tests": {"outcomes": [specialist_item]},
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
        if name == "hidden_robustness_stress":
            return dict(produce()), False
        return artifacts[name], False

    seen = {}

    def fake_robustness(**kwargs):
        seen["specialist_evidence"] = kwargs.get("specialist_evidence")
        return SimpleNamespace(promotion=SimpleNamespace(allowed=True, missing_evidence=frozenset()))

    monkeypatch.setattr(research_brain, "_stage", fake_stage)
    monkeypatch.setattr(
        research_brain,
        "chronological_holdout",
        lambda bars, **kwargs: (tuple(bars[:200]), tuple(bars[200:]), object()),
    )
    monkeypatch.setattr(research_brain, "market_bars_to_nautilus", lambda bars, **kwargs: tuple(bars))
    monkeypatch.setattr(research_brain, "run_generated_robustness_cycle", fake_robustness)
    monkeypatch.setattr(
        research_brain,
        "run_generated_hidden_cycle",
        lambda **kwargs: SimpleNamespace(
            promotion=SimpleNamespace(allowed=True, missing_evidence=frozenset(), reason="hidden passed"),
            hidden_result=SimpleNamespace(total_return=0.1),
        ),
    )

    research_brain.run_research_brain(
        _config(),
        dataset,
        _Memory(),
        code_hash="code-v1",
        lock_hash="lock-v1",
    )

    assert seen["specialist_evidence"] == (evidence,)
