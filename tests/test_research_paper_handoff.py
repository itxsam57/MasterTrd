from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import mastertrd.research_job as research_job
from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome


ROOT = Path(__file__).resolve().parents[1]
AUTONOMOUS_RESEARCH_WORKFLOW = ROOT / ".github" / "workflows" / "autonomous-research.yml"


def _candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-paper-handoff",
        family="trend",
        style="recipe:ema-cross-crypto",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1h",
        entry={"type": "ema_cross", "fast": 10, "slow": 30},
        exit={"type": "cross_reverse"},
    )


def test_research_job_exports_recoverable_public_paper_candidate_manifest(monkeypatch, tmp_path):
    candidate = _candidate()
    plan = research_job.ResearchJobPlan(
        requested_families=("trend",),
        runnable_families=("trend",),
        blocked_families=(),
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed_start=40,
        seed_stop=41,
        archive_months=2,
    )

    class _Memory:
        def get_stage(self, run_id, stage):
            assert run_id == "run-1"
            assert stage == "hidden_robustness_stress"
            return SimpleNamespace(
                artifact={
                    "outcomes": [
                        {
                            "genome": candidate.canonical_payload(),
                            "state": "hidden_pass",
                            "score": 0.12,
                            "reason": "qualified",
                            "qualified_for_paper": True,
                        }
                    ]
                }
            )

        def close(self):
            pass

    memory = _Memory()
    monkeypatch.setattr(research_job, "DuckDbResearchMemory", lambda path: memory)
    monkeypatch.setattr(research_job, "_stable_archive_periods", lambda count: ("2026-05", "2026-06"))
    monkeypatch.setattr(
        research_job,
        "_load_public_instruments",
        lambda ids: {instrument_id: object() for instrument_id in ids},
    )
    monkeypatch.setattr(
        research_job,
        "generate_candidate",
        lambda **kwargs: SimpleNamespace(timeframe="1h"),
    )
    dataset = SimpleNamespace(dataset_hash="dataset-v1")
    monkeypatch.setattr(
        research_job,
        "_dataset_for_timeframe",
        lambda **kwargs: (dataset, ({"file_sha256": "a" * 64},)),
    )
    monkeypatch.setattr(
        research_job,
        "run_research_brain",
        lambda *args, **kwargs: SimpleNamespace(
            run_id="run-1",
            generated=1,
            stored=1,
            paper_queued=1,
            resumed=False,
            finalists=(
                SimpleNamespace(
                    strategy_id=candidate.strategy_id,
                    genome_hash=candidate.genome_hash,
                    state=StrategyState.PAPER,
                    score=0.12,
                    reason="paper_started",
                ),
            ),
        ),
    )

    result = research_job.run_research_job(
        plan,
        artifact_dir=tmp_path,
        code_hash="code-v1",
        lock_hash="lock-v1",
    )

    paper_candidates = result["runs"][0]["paper_candidates"]
    assert paper_candidates == [
        {
            "candidate": candidate.canonical_payload(),
            "strategy_id": candidate.strategy_id,
            "genome_hash": candidate.genome_hash,
            "code_hash": "code-v1",
            "dataset_hash": "dataset-v1",
            "lock_hash": "lock-v1",
            "recipe_id": None,
        }
    ]


def test_autonomous_research_self_starts_when_research_code_lands_on_main():
    text = AUTONOMOUS_RESEARCH_WORKFLOW.read_text(encoding="utf-8")

    assert "  push:\n" in text
    assert "    branches:\n      - main\n" in text
    assert "      - 'src/mastertrd/research_job.py'\n" in text
    assert "      - 'src/mastertrd/research_brain.py'\n" in text
    assert "      - 'src/mastertrd/strategy_universe.py'\n" in text
