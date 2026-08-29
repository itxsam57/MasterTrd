from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Iterable, Mapping

from .contracts import StrategyState
from .genome import StrategyGenome
from .validation import ValidationEvidence, extra_evidence_for_target, validated_evidence_types


_REQUIRED_EVIDENCE: Mapping[StrategyState, frozenset[str]] = {
    StrategyState.SCREENED: frozenset({"screen"}),
    StrategyState.BACKTESTED: frozenset({"nautilus_backtest"}),
    StrategyState.ROBUST: frozenset({"walk_forward", "cost_stress", "parameter_stability"}),
    StrategyState.HIDDEN_PASS: frozenset({"hidden_test"}),
    StrategyState.PAPER: frozenset({"paper_started"}),
    StrategyState.CHALLENGER: frozenset({"paper_minimum_evidence"}),
    StrategyState.CHAMPION: frozenset({"champion_comparison"}),
    StrategyState.LIVE_ELIGIBLE: frozenset({"risk_review", "reconciliation_test", "kill_switch_test"}),
}

_NEXT: Mapping[StrategyState, StrategyState] = {
    StrategyState.IDEA: StrategyState.SCREENED,
    StrategyState.SCREENED: StrategyState.BACKTESTED,
    StrategyState.BACKTESTED: StrategyState.ROBUST,
    StrategyState.ROBUST: StrategyState.HIDDEN_PASS,
    StrategyState.HIDDEN_PASS: StrategyState.PAPER,
    StrategyState.PAPER: StrategyState.CHALLENGER,
    StrategyState.CHALLENGER: StrategyState.CHAMPION,
    StrategyState.CHAMPION: StrategyState.LIVE_ELIGIBLE,
}


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    allowed: bool
    target: StrategyState
    missing_evidence: frozenset[str] = frozenset()
    reason: str = ""


def evaluate_promotion(current: StrategyState, target: StrategyState, evidence: AbstractSet[str]) -> PromotionDecision:
    if target in {StrategyState.REJECTED, StrategyState.QUARANTINED}:
        return PromotionDecision(True, target, reason="fail-safe terminal transition")
    expected = _NEXT.get(current)
    if expected != target:
        return PromotionDecision(False, target, reason=f"illegal transition {current}->{target}")
    required = _REQUIRED_EVIDENCE[target]
    missing = frozenset(required.difference(evidence))
    if missing:
        return PromotionDecision(False, target, missing, "required evidence missing")
    return PromotionDecision(True, target, reason="all promotion gates satisfied")


def evaluate_validated_promotion(
    current: StrategyState,
    target: StrategyState,
    genome: StrategyGenome,
    records: Iterable[ValidationEvidence],
) -> PromotionDecision:
    evidence = validated_evidence_types(genome, records)
    base = evaluate_promotion(current, target, evidence)
    if not base.allowed:
        return base
    if target in {StrategyState.REJECTED, StrategyState.QUARANTINED}:
        return base
    extra_required = extra_evidence_for_target(genome, target)
    missing = frozenset(extra_required.difference(evidence))
    if missing:
        return PromotionDecision(False, target, missing, "family-specific validation evidence missing")
    return PromotionDecision(True, target, reason="validated promotion evidence satisfied")
