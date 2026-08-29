from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from statistics import fmean
from typing import Sequence

from .contracts import EvaluationResult
from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class AdvancedValidationPolicy:
    min_evaluations: int
    min_trades_per_evaluation: int
    min_positive_ratio: float
    max_drawdown: float
    min_monte_carlo_survival_ratio: float
    max_monte_carlo_loss: float

    def __post_init__(self) -> None:
        if self.min_evaluations <= 0:
            raise ValueError("min_evaluations must be positive")
        if self.min_trades_per_evaluation <= 0:
            raise ValueError("min_trades_per_evaluation must be positive")
        values = (
            self.min_positive_ratio,
            self.max_drawdown,
            self.min_monte_carlo_survival_ratio,
            self.max_monte_carlo_loss,
        )
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("advanced validation thresholds must be finite")
        if not 0.0 <= self.min_positive_ratio <= 1.0:
            raise ValueError("min_positive_ratio must be between 0 and 1")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ValueError("max_drawdown must be between 0 and 1")
        if not 0.0 <= self.min_monte_carlo_survival_ratio <= 1.0:
            raise ValueError("min_monte_carlo_survival_ratio must be between 0 and 1")


def _validate_evaluations(
    candidate: StrategyGenome,
    evaluations: Sequence[EvaluationResult],
    policy: AdvancedValidationPolicy,
) -> None:
    if len(evaluations) < policy.min_evaluations:
        raise ValueError("evaluations must satisfy min_evaluations")

    first = evaluations[0]
    for item in evaluations:
        if item.strategy_id != candidate.strategy_id:
            raise ValueError("strategy_id does not match candidate")
        if item.genome_hash != candidate.genome_hash:
            raise ValueError("genome_hash does not match candidate")
        if item.code_hash != first.code_hash:
            raise ValueError("all evaluations must share code_hash")
        if item.engine != first.engine:
            raise ValueError("all evaluations must use the same engine")
        if item.engine_version != first.engine_version:
            raise ValueError("all evaluations must share engine_version")

    dataset_hashes = [item.dataset_hash for item in evaluations]
    if len(set(dataset_hashes)) != len(dataset_hashes):
        raise ValueError("evaluation dataset_hash values must be unique")


def _aggregate_dataset_hash(evaluations: Sequence[EvaluationResult]) -> str:
    payload = json.dumps(
        [item.dataset_hash for item in evaluations],
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def purged_cpcv_evidence(
    candidate: StrategyGenome,
    evaluations: Sequence[EvaluationResult],
    policy: AdvancedValidationPolicy,
) -> ValidationEvidence:
    _validate_evaluations(candidate, evaluations, policy)
    first = evaluations[0]

    positive_count = sum(item.total_return > 0.0 for item in evaluations)
    positive_ratio = positive_count / len(evaluations)
    minimum_trade_count = min(item.trade_count for item in evaluations)
    worst_drawdown = max(item.max_drawdown for item in evaluations)
    passed = (
        minimum_trade_count >= policy.min_trades_per_evaluation
        and positive_ratio >= policy.min_positive_ratio
        and worst_drawdown <= policy.max_drawdown
    )

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="purged_cpcv",
        dataset_hash=_aggregate_dataset_hash(evaluations),
        code_hash=first.code_hash,
        engine=first.engine,
        engine_version=first.engine_version,
        passed=passed,
        metrics={
            "evaluation_count": float(len(evaluations)),
            "positive_evaluation_ratio": float(positive_ratio),
            "minimum_trade_count": float(minimum_trade_count),
            "worst_drawdown": float(worst_drawdown),
            "average_total_return": float(fmean(item.total_return for item in evaluations)),
        },
    )


def monte_carlo_evidence(
    candidate: StrategyGenome,
    evaluations: Sequence[EvaluationResult],
    policy: AdvancedValidationPolicy,
) -> ValidationEvidence:
    _validate_evaluations(candidate, evaluations, policy)
    first = evaluations[0]

    survival_count = sum(item.total_return >= policy.max_monte_carlo_loss for item in evaluations)
    survival_ratio = survival_count / len(evaluations)
    minimum_trade_count = min(item.trade_count for item in evaluations)
    worst_drawdown = max(item.max_drawdown for item in evaluations)
    worst_total_return = min(item.total_return for item in evaluations)
    passed = (
        minimum_trade_count >= policy.min_trades_per_evaluation
        and survival_ratio >= policy.min_monte_carlo_survival_ratio
        and worst_drawdown <= policy.max_drawdown
    )

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="monte_carlo",
        dataset_hash=_aggregate_dataset_hash(evaluations),
        code_hash=first.code_hash,
        engine=first.engine,
        engine_version=first.engine_version,
        passed=passed,
        metrics={
            "path_count": float(len(evaluations)),
            "survival_ratio": float(survival_ratio),
            "minimum_trade_count": float(minimum_trade_count),
            "worst_drawdown": float(worst_drawdown),
            "worst_total_return": float(worst_total_return),
            "average_total_return": float(fmean(item.total_return for item in evaluations)),
        },
    )
