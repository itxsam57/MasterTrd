from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from statistics import mean
from typing import Iterable, Sequence

from .contracts import EvaluationResult
from .genome import StrategyGenome
from .holdout import HoldoutManifest
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class HiddenGatePolicy:
    min_trades_per_evaluation: int
    min_total_return: float
    max_drawdown: float
    min_regime_pass_ratio: float

    def __post_init__(self) -> None:
        if self.min_trades_per_evaluation <= 0:
            raise ValueError("min_trades_per_evaluation must be positive")
        if not 0.0 <= float(self.max_drawdown) <= 1.0:
            raise ValueError("max_drawdown must be between 0 and 1")
        if not 0.0 <= float(self.min_regime_pass_ratio) <= 1.0:
            raise ValueError("min_regime_pass_ratio must be between 0 and 1")


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


def _evaluation_passes(result: EvaluationResult, policy: HiddenGatePolicy) -> bool:
    return (
        result.engine == "nautilus_trader"
        and result.trade_count >= policy.min_trades_per_evaluation
        and result.total_return >= policy.min_total_return
        and result.max_drawdown <= policy.max_drawdown
        and float(result.scores.get("execution_backtest", 0.0)) > 0.0
    )


def hidden_test_evidence(
    candidate: StrategyGenome,
    result: EvaluationResult,
    manifest: HoldoutManifest,
    policy: HiddenGatePolicy,
) -> ValidationEvidence:
    _require_candidate(result, candidate)
    if result.dataset_hash != manifest.manifest_hash:
        raise ValueError("hidden result dataset_hash must equal manifest_hash")

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="hidden_test",
        dataset_hash=manifest.manifest_hash,
        code_hash=result.code_hash,
        engine=result.engine,
        engine_version=result.engine_version,
        passed=_evaluation_passes(result, policy),
        metrics={
            "hidden_observation_count": float(manifest.hidden_count),
            "total_return": float(result.total_return),
            "max_drawdown": float(result.max_drawdown),
            "trade_count": float(result.trade_count),
        },
    )


def regime_test_evidence(
    candidate: StrategyGenome,
    regimes: Iterable[EvaluationResult],
    policy: HiddenGatePolicy,
) -> ValidationEvidence:
    records = list(regimes)
    code_hash, engine, engine_version = _require_common_identity(records)
    for record in records:
        _require_candidate(record, candidate)

    passing = sum(_evaluation_passes(record, policy) for record in records)
    ratio = round(passing / len(records), 2)
    worst_drawdown = max(record.max_drawdown for record in records)
    average_return = mean(record.total_return for record in records)

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="regime_test",
        dataset_hash=_aggregate_hash([record.dataset_hash for record in records]),
        code_hash=code_hash,
        engine=engine,
        engine_version=engine_version,
        passed=ratio >= policy.min_regime_pass_ratio,
        metrics={
            "regime_count": float(len(records)),
            "passing_regime_count": float(passing),
            "passing_regime_ratio": ratio,
            "average_total_return": float(average_return),
            "worst_drawdown": float(worst_drawdown),
        },
    )
