from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .contracts import EvaluationResult, StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .memory_duckdb import DuckDbResearchMemory, DurableResearchRecord
from .nautilus_evaluation import run_binance_spot_evaluation
from .validation import ValidationEvidence, nautilus_backtest_evidence


@dataclass(frozen=True, slots=True)
class GeneratedBacktestCycle:
    result: EvaluationResult
    evidence: ValidationEvidence
    promotion: PromotionDecision
    record: DurableResearchRecord


def run_generated_backtest_cycle(
    *,
    experiment_id: str,
    candidate: StrategyGenome,
    instrument,
    data: Iterable[object],
    dataset_hash: str,
    code_hash: str,
    trade_size: str,
    memory: DuckDbResearchMemory,
    starting_balances: Sequence[str] = ("100000 USDT",),
    fees: float = 0.0,
    slippage: float = 0.0,
) -> GeneratedBacktestCycle:
    if not experiment_id:
        raise ValueError("experiment_id is required")
    if not trade_size:
        raise ValueError("trade_size is required")

    result = run_binance_spot_evaluation(
        genome=candidate,
        instrument=instrument,
        data=data,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        fees=fees,
        slippage=slippage,
        starting_balances=starting_balances,
        trade_size_override=trade_size,
    )
    evidence = nautilus_backtest_evidence(result)
    promotion = evaluate_validated_promotion(
        StrategyState.SCREENED,
        StrategyState.BACKTESTED,
        candidate,
        [evidence],
    )
    status = StrategyState.BACKTESTED.value if promotion.allowed else StrategyState.SCREENED.value
    reason = promotion.reason if promotion.allowed else "; ".join(sorted(promotion.missing_evidence)) or promotion.reason
    record = memory.append(
        experiment_id=experiment_id,
        genome=candidate,
        status=status,
        engine=result.engine,
        score=float(result.total_return),
        reason=reason,
        metadata={
            "dataset_hash": result.dataset_hash,
            "code_hash": result.code_hash,
            "evidence_hash": evidence.evidence_hash,
            "evidence_type": evidence.evidence_type,
            "evidence_passed": evidence.passed,
            "promotion_allowed": promotion.allowed,
            "trade_count": result.trade_count,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
        },
    )
    return GeneratedBacktestCycle(
        result=result,
        evidence=evidence,
        promotion=promotion,
        record=record,
    )
