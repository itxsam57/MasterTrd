from __future__ import annotations

from types import SimpleNamespace

import mastertrd.research_job as research_job
from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome


def test_paper_candidate_manifest_uses_strategy_state_enum_value():
    candidate = StrategyGenome(
        strategy_id="R-PAPER-1",
        family="trend",
        style="ema_cross",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="4h",
        entry={"fast": 12, "slow": 26},
        exit={"signal": "reverse"},
    )
    report = SimpleNamespace(
        run_id="run-paper-1",
        finalists=(
            SimpleNamespace(
                strategy_id=candidate.strategy_id,
                genome_hash=candidate.genome_hash,
                state=StrategyState.PAPER,
            ),
        ),
    )
    memory = SimpleNamespace(
        get_stage=lambda run_id, stage: SimpleNamespace(
            artifact={"outcomes": [{"genome": candidate.canonical_payload()}]}
        )
    )

    manifests = research_job._paper_candidate_manifests(
        report=report,
        memory=memory,
        code_hash="code-v1",
        dataset_hash="dataset-v1",
        lock_hash="lock-v1",
        recipe_id="ema-cross-balanced",
    )

    assert manifests == [
        {
            "candidate": candidate.canonical_payload(),
            "strategy_id": candidate.strategy_id,
            "genome_hash": candidate.genome_hash,
            "code_hash": "code-v1",
            "dataset_hash": "dataset-v1",
            "lock_hash": "lock-v1",
            "recipe_id": "ema-cross-balanced",
        }
    ]
