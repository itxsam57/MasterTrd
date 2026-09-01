from __future__ import annotations

from dataclasses import dataclass

from .contracts import StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .nautilus_paper import probe_nautilus_sandbox_session
from .paper_archive import JsonPaperReportArchive
from .paper_evidence import PaperStartReceipt, paper_started_evidence
from .paper_forward import PaperForwardReport
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
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


def finalize_forward_paper_session(
    *,
    journal: PaperSessionJournal,
    session_store: JsonPaperSessionStore,
    archive: JsonPaperReportArchive,
    ended_ns: int,
) -> PaperForwardReport:
    """Persist and archive one forward PAPER session exactly once.

    Final session state is written before the report archive. If the process
    crashes between those two durable writes, a restart reloads the immutable
    final report from the session store and safely retries the idempotent archive
    append. Direct journal finalization remains one-shot and immutable.
    """

    report = journal.finalized_report
    if report is None:
        report = journal.finalize(ended_ns=ended_ns)
        session_store.save(journal)
    archive.append(report)
    return report
