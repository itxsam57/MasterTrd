from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class ChampionComparisonPolicy:
    min_closed_trades: int
    min_score_improvement: float
    max_drawdown_ratio: float

    def __post_init__(self) -> None:
        if self.min_closed_trades <= 0:
            raise ValueError("min_closed_trades must be positive")
        if not isfinite(float(self.min_score_improvement)) or self.min_score_improvement < 0:
            raise ValueError("min_score_improvement must be finite and non-negative")
        if not isfinite(float(self.max_drawdown_ratio)) or self.max_drawdown_ratio <= 0:
            raise ValueError("max_drawdown_ratio must be finite and positive")


def _paper_metric(record: ValidationEvidence, name: str) -> float:
    if name not in record.metrics:
        raise ValueError(f"paper evidence missing metric {name}")
    value = float(record.metrics[name])
    if not isfinite(value):
        raise ValueError(f"paper metric {name} must be finite")
    return value


def _validate_paper_identity(record: ValidationEvidence) -> None:
    if record.evidence_type != "paper_minimum_evidence":
        raise ValueError("comparison requires paper_minimum_evidence")
    if record.engine != "nautilus_trader":
        raise ValueError("paper evidence engine must be nautilus_trader")


def _score(record: ValidationEvidence) -> float:
    # Deliberately simple and auditable: reward forward return, penalize drawdown.
    return _paper_metric(record, "total_return") - _paper_metric(record, "max_drawdown")


def champion_comparison_evidence(
    candidate: StrategyGenome,
    challenger_paper: ValidationEvidence,
    incumbent_paper: ValidationEvidence | None,
    policy: ChampionComparisonPolicy,
) -> ValidationEvidence:
    _validate_paper_identity(challenger_paper)
    if challenger_paper.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if challenger_paper.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")

    challenger_trades = _paper_metric(challenger_paper, "closed_trades")
    challenger_return = _paper_metric(challenger_paper, "total_return")
    challenger_drawdown = _paper_metric(challenger_paper, "max_drawdown")
    challenger_reconciliation_errors = _paper_metric(challenger_paper, "reconciliation_errors")
    challenger_score = _score(challenger_paper)

    if incumbent_paper is None:
        incumbent_present = 0.0
        incumbent_score = 0.0
        incumbent_drawdown = 0.0
        score_improvement = challenger_score
        drawdown_ok = True
    else:
        _validate_paper_identity(incumbent_paper)
        if incumbent_paper.strategy_id == candidate.strategy_id:
            raise ValueError("incumbent must be a different strategy_id")
        incumbent_present = 1.0
        incumbent_score = _score(incumbent_paper)
        incumbent_drawdown = _paper_metric(incumbent_paper, "max_drawdown")
        score_improvement = challenger_score - incumbent_score
        if incumbent_drawdown == 0.0:
            drawdown_ok = challenger_drawdown == 0.0
        else:
            drawdown_ok = challenger_drawdown <= incumbent_drawdown * policy.max_drawdown_ratio

    passed = (
        challenger_paper.passed
        and challenger_trades >= policy.min_closed_trades
        and challenger_reconciliation_errors == 0.0
        and (
            incumbent_paper is None
            or (
                incumbent_paper.passed
                and score_improvement >= policy.min_score_improvement
                and drawdown_ok
            )
        )
    )

    identity_material = "|".join(
        (
            challenger_paper.evidence_hash,
            incumbent_paper.evidence_hash if incumbent_paper is not None else "FIRST_CHAMPION",
        )
    ).encode()
    comparison_hash = hashlib.sha256(identity_material).hexdigest()

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="champion_comparison",
        dataset_hash=comparison_hash,
        code_hash=candidate.genome_hash,
        engine="nautilus_trader",
        engine_version=challenger_paper.engine_version,
        passed=passed,
        metrics={
            "incumbent_present": incumbent_present,
            "challenger_score": challenger_score,
            "incumbent_score": incumbent_score,
            "score_improvement": score_improvement,
            "challenger_total_return": challenger_return,
            "challenger_max_drawdown": challenger_drawdown,
            "incumbent_max_drawdown": incumbent_drawdown,
            "closed_trades": challenger_trades,
            "reconciliation_errors": challenger_reconciliation_errors,
            "drawdown_ok": 1.0 if drawdown_ok else 0.0,
        },
    )
