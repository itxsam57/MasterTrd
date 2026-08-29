from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .contracts import EvaluationResult, StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .hidden_gate import HiddenGatePolicy, hidden_test_evidence, regime_test_evidence
from .holdout import HoldoutManifest
from .nautilus_evaluation import run_binance_spot_evaluation
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class GeneratedHiddenCycle:
    hidden_result: EvaluationResult
    regime_results: tuple[EvaluationResult, ...]
    evidence: tuple[ValidationEvidence, ...]
    promotion: PromotionDecision


def run_generated_hidden_cycle(
    *,
    candidate: StrategyGenome,
    instrument,
    hidden_data: Iterable[object],
    manifest: HoldoutManifest,
    regime_datasets: Sequence[tuple[str, Iterable[object]]],
    code_hash: str,
    trade_size: str,
    policy: HiddenGatePolicy,
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> GeneratedHiddenCycle:
    hidden_events = tuple(hidden_data)
    if len(hidden_events) != manifest.hidden_count:
        raise ValueError("hidden data count must match frozen holdout manifest")
    if not regime_datasets:
        raise ValueError("regime datasets are required")

    common = dict(
        genome=candidate,
        instrument=instrument,
        code_hash=code_hash,
        trade_size_override=trade_size,
        starting_balances=starting_balances,
    )
    hidden_result = run_binance_spot_evaluation(
        data=hidden_events,
        dataset_hash=manifest.manifest_hash,
        **common,
    )
    regime_results = tuple(
        run_binance_spot_evaluation(
            data=tuple(regime_data),
            dataset_hash=regime_hash,
            **common,
        )
        for regime_hash, regime_data in regime_datasets
    )

    evidence = (
        hidden_test_evidence(candidate, hidden_result, manifest, policy),
        regime_test_evidence(candidate, regime_results, policy),
    )
    promotion = evaluate_validated_promotion(
        StrategyState.ROBUST,
        StrategyState.HIDDEN_PASS,
        candidate,
        evidence,
    )
    return GeneratedHiddenCycle(
        hidden_result=hidden_result,
        regime_results=regime_results,
        evidence=evidence,
        promotion=promotion,
    )
