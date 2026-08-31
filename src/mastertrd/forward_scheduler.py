from __future__ import annotations

from dataclasses import dataclass

from .champion import ChampionComparisonPolicy, champion_comparison_evidence
from .contracts import StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .paper_archive import JsonPaperReportArchive
from .paper_challenger import evaluate_archived_challenger
from .paper_forward import PaperMinimumPolicy
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class ForwardPromotionCycle:
    paper_evidence: ValidationEvidence
    challenger_promotion: PromotionDecision
    champion_evidence: ValidationEvidence | None
    champion_promotion: PromotionDecision | None


class ForwardPromotionScheduler:
    """Evaluate persistent forward evidence through the governed lifecycle.

    The scheduler owns ordering only. PAPER minimum policy, incumbent comparison,
    and lifecycle legality stay in their existing evidence producers/Governor so
    there is one promotion authority and no shortcut around CHALLENGER.
    """

    def __init__(
        self,
        *,
        paper_policy: PaperMinimumPolicy,
        champion_policy: ChampionComparisonPolicy,
    ) -> None:
        self._paper_policy = paper_policy
        self._champion_policy = champion_policy

    def evaluate(
        self,
        *,
        candidate: StrategyGenome,
        archive: JsonPaperReportArchive,
        incumbent_paper: ValidationEvidence | None,
    ) -> ForwardPromotionCycle:
        challenger = evaluate_archived_challenger(
            candidate=candidate,
            archive=archive,
            policy=self._paper_policy,
        )
        if not challenger.promotion.allowed:
            return ForwardPromotionCycle(
                paper_evidence=challenger.evidence,
                challenger_promotion=challenger.promotion,
                champion_evidence=None,
                champion_promotion=None,
            )

        comparison = champion_comparison_evidence(
            candidate,
            challenger.evidence,
            incumbent_paper,
            self._champion_policy,
        )
        champion_promotion = evaluate_validated_promotion(
            StrategyState.CHALLENGER,
            StrategyState.CHAMPION,
            candidate,
            [comparison],
        )
        return ForwardPromotionCycle(
            paper_evidence=challenger.evidence,
            challenger_promotion=challenger.promotion,
            champion_evidence=comparison,
            champion_promotion=champion_promotion,
        )
