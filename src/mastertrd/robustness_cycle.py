from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .contracts import EvaluationResult, StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .nautilus_evaluation import run_binance_spot_evaluation
from .robustness import (
    RobustnessPolicy,
    cost_stress_evidence,
    parameter_stability_evidence,
    walk_forward_evidence,
)
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class GeneratedRobustnessCycle:
    base_result: EvaluationResult
    stressed_result: EvaluationResult
    fold_results: tuple[EvaluationResult, ...]
    neighbor_results: tuple[EvaluationResult, ...]
    evidence: tuple[ValidationEvidence, ...]
    promotion: PromotionDecision


def _ema_neighbors(candidate: StrategyGenome) -> tuple[StrategyGenome, ...]:
    entry = dict(candidate.entry)
    kind = entry.get("kind", entry.get("type"))
    if kind != "ema_cross":
        raise ValueError("automatic parameter neighborhood currently supports ema_cross only")

    fast_key = "fast_period" if "fast_period" in entry else "fast"
    slow_key = "slow_period" if "slow_period" in entry else "slow"
    if fast_key not in entry or slow_key not in entry:
        raise ValueError("ema_cross requires fast and slow parameters")

    fast = int(entry[fast_key])
    slow = int(entry[slow_key])
    variants: list[tuple[int, int]] = []
    for new_fast, new_slow in (
        (fast - 1, slow),
        (fast + 1, slow),
        (fast, slow - 1),
        (fast, slow + 1),
    ):
        if new_fast > 0 and new_fast < new_slow and (new_fast, new_slow) != (fast, slow):
            if (new_fast, new_slow) not in variants:
                variants.append((new_fast, new_slow))

    if len(variants) < 2:
        raise ValueError("ema_cross parameter neighborhood is too small")

    neighbors = []
    for new_fast, new_slow in variants:
        neighbor_entry = dict(entry)
        neighbor_entry[fast_key] = new_fast
        neighbor_entry[slow_key] = new_slow
        neighbors.append(
            StrategyGenome(
                strategy_id=candidate.strategy_id,
                family=candidate.family,
                style=candidate.style,
                instruments=tuple(candidate.instruments),
                timeframe=candidate.timeframe,
                entry=neighbor_entry,
                exit=dict(candidate.exit),
                filters=dict(candidate.filters),
                risk=dict(candidate.risk),
                data_requirements=tuple(candidate.data_requirements),
                allow_short=candidate.allow_short,
            )
        )
    return tuple(neighbors)


def run_generated_robustness_cycle(
    *,
    candidate: StrategyGenome,
    instrument,
    data: Iterable[object],
    dataset_hash: str,
    fold_datasets: Sequence[tuple[str, Iterable[object]]],
    code_hash: str,
    trade_size: str,
    policy: RobustnessPolicy,
    stressed_fees: float,
    stressed_slippage: float,
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> GeneratedRobustnessCycle:
    base_events = tuple(data)
    if not base_events:
        raise ValueError("base robustness dataset is required")
    if not fold_datasets:
        raise ValueError("walk-forward fold datasets are required")
    if stressed_fees <= 0.0 and stressed_slippage <= 0.0:
        raise ValueError("cost stress must increase fees or slippage")

    common = dict(
        instrument=instrument,
        code_hash=code_hash,
        trade_size_override=trade_size,
        starting_balances=starting_balances,
    )
    base_result = run_binance_spot_evaluation(
        genome=candidate,
        data=base_events,
        dataset_hash=dataset_hash,
        **common,
    )
    stressed_result = run_binance_spot_evaluation(
        genome=candidate,
        data=base_events,
        dataset_hash=dataset_hash,
        fees=stressed_fees,
        slippage=stressed_slippage,
        **common,
    )

    fold_results = tuple(
        run_binance_spot_evaluation(
            genome=candidate,
            data=tuple(fold_data),
            dataset_hash=fold_hash,
            **common,
        )
        for fold_hash, fold_data in fold_datasets
    )

    neighbors = _ema_neighbors(candidate)
    neighbor_results = tuple(
        run_binance_spot_evaluation(
            genome=neighbor,
            data=base_events,
            dataset_hash=dataset_hash,
            **common,
        )
        for neighbor in neighbors
    )

    evidence = (
        walk_forward_evidence(candidate, fold_results, policy),
        cost_stress_evidence(candidate, base_result, stressed_result, policy),
        parameter_stability_evidence(candidate, base_result, neighbor_results, policy),
    )
    promotion = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        candidate,
        evidence,
    )
    return GeneratedRobustnessCycle(
        base_result=base_result,
        stressed_result=stressed_result,
        fold_results=fold_results,
        neighbor_results=neighbor_results,
        evidence=evidence,
        promotion=promotion,
    )
