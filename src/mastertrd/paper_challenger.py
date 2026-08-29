from __future__ import annotations

from dataclasses import dataclass

from .contracts import StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .paper_archive import JsonPaperReportArchive
from .paper_forward import PaperMinimumPolicy, paper_minimum_evidence
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class ArchivedChallengerCycle:
    evidence: ValidationEvidence
    promotion: PromotionDecision
    report_count: int


def evaluate_archived_challenger(
    *,
    candidate: StrategyGenome,
    archive: JsonPaperReportArchive,
    policy: PaperMinimumPolicy,
) -> ArchivedChallengerCycle:
    reports = archive.load()
    evidence = paper_minimum_evidence(candidate, reports, policy)
    promotion = evaluate_validated_promotion(
        StrategyState.PAPER,
        StrategyState.CHALLENGER,
        candidate,
        [evidence],
    )
    return ArchivedChallengerCycle(
        evidence=evidence,
        promotion=promotion,
        report_count=len(reports),
    )
