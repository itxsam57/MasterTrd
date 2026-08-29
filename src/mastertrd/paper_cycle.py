from __future__ import annotations

from dataclasses import dataclass

from .contracts import StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .nautilus_paper import probe_nautilus_sandbox_session
from .paper_evidence import PaperStartReceipt, paper_started_evidence
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class PaperStartCycle:
    receipt: PaperStartReceipt
    evidence: ValidationEvidence
    promotion: PromotionDecision


def start_generated_paper_cycle(
    *,
    candidate: StrategyGenome,
    session_nonce: str,
) -> PaperStartCycle:
    if not session_nonce:
        raise ValueError("session_nonce is required")

    receipt = probe_nautilus_sandbox_session(
        candidate,
        session_nonce=session_nonce,
    )
    evidence = paper_started_evidence(candidate, receipt)
    promotion = evaluate_validated_promotion(
        StrategyState.HIDDEN_PASS,
        StrategyState.PAPER,
        candidate,
        [evidence],
    )
    return PaperStartCycle(
        receipt=receipt,
        evidence=evidence,
        promotion=promotion,
    )
