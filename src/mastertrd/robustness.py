from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from statistics import mean
from typing import Iterable, Sequence

from .contracts import EvaluationResult
from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class RobustnessPolicy:
    min_trades_per_slice: int
    min_profitable_slice_ratio: float
    max_drawdown: float
    min_stressed_return: float
    max_return_degradation: float
    min_stable_neighbor_ratio: float

    def __post_init__(self) -> None:
        if self.min_trades_per_slice <= 0:
            raise ValueError("min_trades_per_slice must be positive")
        for name in (
            "min_profitable_slice_ratio",
            "max_drawdown",
            "max_return_degradation",
            "min_stable_neighbor_ratio",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


def _aggregate_hash(values: Sequence[str]) -> str:
    encoded = json.dumps(list(values), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_candidate(result: EvaluationResult, candidate: StrategyGenome) -> None:
    if result.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if result.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")


def _require_common_identity(results: Sequence[EvaluationResult]) -> tuple[str, str, str]:
    if not results:
        raise ValueError("at least one evaluation result is required")
    code_hash = results[0].code_hash
    engine = results[0].engine
    engine_version = results[0].engine_version
    for result in results[1:]:
        if result.code_hash != code_hash:
            raise ValueError("all results must use the same code_hash")
        if result.engine != engine:
            raise ValueError("all results must use the same engine")
        if result.engine_version != engine_version:
            raise ValueError("all results must use the same engine_version")
    return code_hash, engine, engine_version


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    # Evidence ratios are reported to two decimal places. This also makes
    # policies such as 0.67 express the conventional two-out-of-three gate.
    return round(numerator / denominator, 2)


def walk_forward_evidence(
    candidate: StrategyGenome,
    folds: Iterable[EvaluationResult],
    policy: RobustnessPolicy,
) -> ValidationEvidence:
    records = list(folds)
    code_hash, engine, engine_version = _require_common_identity(records)
    for record in records:
        _require_candidate(record, candidate)

    profitable_ratio = _ratio(sum(record.total_return > 0.0 for record in records), len(records))
    minimum_trades = min(record.trade_count for record in records)
    worst_drawdown = max(record.max_drawdown for record in records)
    average_return = mean(record.total_return for record in records)
    passed = (
        minimum_trades >= policy.min_trades_per_slice
        and profitable_ratio >= policy.min_profitable_slice_ratio
        and worst_drawdown <= policy.max_drawdown
    )

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="walk_forward",
        dataset_hash=_aggregate_hash([record.dataset_hash for record in records]),
        code_hash=code_hash,
        engine=engine,
        engine_version=engine_version,
        passed=passed,
        metrics={
            "fold_count": float(len(records)),
            "profitable_slice_ratio": profitable_ratio,
            "minimum_trade_count": float(minimum_trades),
            "worst_drawdown": float(worst_drawdown),
            "average_total_return": float(average_return),
        },
    )


def cost_stress_evidence(
    candidate: StrategyGenome,
    base: EvaluationResult,
    stressed: EvaluationResult,
    policy: RobustnessPolicy,
) -> ValidationEvidence:
    _require_candidate(base, candidate)
    _require_candidate(stressed, candidate)
    _require_common_identity([base, stressed])
    if stressed.dataset_hash != base.dataset_hash:
        raise ValueError("cost stress must use the same dataset_hash")
    if stressed.fees <= base.fees and stressed.slippage <= base.slippage:
        raise ValueError("cost stress requires higher fees or slippage")

    if base.total_return > 0.0:
        degradation = max(0.0, (base.total_return - stressed.total_return) / base.total_return)
    else:
        degradation = 0.0 if stressed.total_return >= base.total_return else 1.0
    passed = (
        stressed.trade_count >= policy.min_trades_per_slice
        and stressed.max_drawdown <= policy.max_drawdown
        and stressed.total_return >= policy.min_stressed_return
        and degradation <= policy.max_return_degradation
    )

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="cost_stress",
        dataset_hash=base.dataset_hash,
        code_hash=base.code_hash,
        engine=base.engine,
        engine_version=base.engine_version,
        passed=passed,
        metrics={
            "base_return": float(base.total_return),
            "stressed_return": float(stressed.total_return),
            "return_degradation": float(degradation),
            "stressed_drawdown": float(stressed.max_drawdown),
            "base_fees": float(base.fees),
            "stressed_fees": float(stressed.fees),
            "base_slippage": float(base.slippage),
            "stressed_slippage": float(stressed.slippage),
        },
    )


def parameter_stability_evidence(
    candidate: StrategyGenome,
    center: EvaluationResult,
    neighbors: Iterable[EvaluationResult],
    policy: RobustnessPolicy,
) -> ValidationEvidence:
    _require_candidate(center, candidate)
    records = list(neighbors)
    if not records:
        raise ValueError("at least one parameter neighbor is required")
    code_hash, engine, engine_version = _require_common_identity([center, *records])
    for record in records:
        if record.strategy_id != candidate.strategy_id:
            raise ValueError("neighbor strategy_id does not match candidate")
        if record.dataset_hash != center.dataset_hash:
            raise ValueError("parameter neighbors must use the same dataset_hash")

    if center.total_return > 0.0:
        floor = center.total_return * (1.0 - policy.max_return_degradation)
    else:
        floor = center.total_return
    stable = [
        record
        for record in records
        if record.trade_count >= policy.min_trades_per_slice
        and record.max_drawdown <= policy.max_drawdown
        and record.total_return >= floor
    ]
    stable_ratio = _ratio(len(stable), len(records))
    passed = stable_ratio >= policy.min_stable_neighbor_ratio

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="parameter_stability",
        dataset_hash=center.dataset_hash,
        code_hash=code_hash,
        engine=engine,
        engine_version=engine_version,
        passed=passed,
        metrics={
            "neighbor_count": float(len(records)),
            "stable_neighbor_ratio": stable_ratio,
            "center_return": float(center.total_return),
            "minimum_acceptable_neighbor_return": float(floor),
            "worst_neighbor_drawdown": float(max(record.max_drawdown for record in records)),
        },
    )
