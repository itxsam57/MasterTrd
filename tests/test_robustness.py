from dataclasses import replace

import pytest

from mastertrd.contracts import EvaluationResult, StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.robustness import (
    RobustnessPolicy,
    cost_stress_evidence,
    parameter_stability_evidence,
    walk_forward_evidence,
)


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-robust-trend",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def result(
    candidate: StrategyGenome,
    *,
    dataset_hash: str,
    total_return: float = 0.10,
    drawdown: float = 0.08,
    trades: int = 20,
    fees: float = 0.001,
    slippage: float = 0.001,
) -> EvaluationResult:
    return EvaluationResult(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash=dataset_hash,
        code_hash="c" * 64,
        engine="nautilus_trader",
        engine_version="1.231.0",
        total_return=total_return,
        sharpe=1.1,
        sortino=1.4,
        max_drawdown=drawdown,
        profit_factor=1.3,
        expectancy=0.005,
        trade_count=trades,
        turnover=0.5,
        fees=fees,
        slippage=slippage,
        scores={"execution_backtest": 1.0},
    )


def policy() -> RobustnessPolicy:
    return RobustnessPolicy(
        min_trades_per_slice=5,
        min_profitable_slice_ratio=0.67,
        max_drawdown=0.20,
        min_stressed_return=0.0,
        max_return_degradation=0.60,
        min_stable_neighbor_ratio=0.67,
    )


def test_all_three_robustness_records_allow_promotion():
    candidate = genome()
    folds = [
        result(candidate, dataset_hash="1" * 64, total_return=0.08),
        result(candidate, dataset_hash="2" * 64, total_return=0.04),
        result(candidate, dataset_hash="3" * 64, total_return=-0.01),
    ]
    walk = walk_forward_evidence(candidate, folds, policy())

    base = result(candidate, dataset_hash="b" * 64, total_return=0.10)
    stressed = replace(base, total_return=0.05, fees=0.003, slippage=0.004)
    cost = cost_stress_evidence(candidate, base, stressed, policy())

    neighbors = [
        result(candidate, dataset_hash="b" * 64, total_return=0.08),
        result(candidate, dataset_hash="b" * 64, total_return=0.06),
        result(candidate, dataset_hash="b" * 64, total_return=-0.02),
    ]
    stability = parameter_stability_evidence(candidate, base, neighbors, policy())

    assert walk.passed is True
    assert cost.passed is True
    assert stability.passed is True
    assert len({walk.evidence_hash, cost.evidence_hash, stability.evidence_hash}) == 3

    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        candidate,
        [walk, cost, stability],
    )
    assert decision.allowed is True


def test_walk_forward_rejects_mixed_code_identity():
    candidate = genome()
    first = result(candidate, dataset_hash="1" * 64)
    second = replace(result(candidate, dataset_hash="2" * 64), code_hash="x" * 64)
    with pytest.raises(ValueError, match="code_hash"):
        walk_forward_evidence(candidate, [first, second], policy())


def test_cost_stress_requires_stricter_costs_and_rejects_excessive_degradation():
    candidate = genome()
    base = result(candidate, dataset_hash="b" * 64, total_return=0.10)
    not_stressed = replace(base, total_return=0.09)
    with pytest.raises(ValueError, match="higher fees or slippage"):
        cost_stress_evidence(candidate, base, not_stressed, policy())

    bad = replace(base, total_return=-0.05, fees=0.004, slippage=0.005)
    evidence = cost_stress_evidence(candidate, base, bad, policy())
    assert evidence.passed is False


def test_parameter_stability_rejects_weak_neighborhood():
    candidate = genome()
    center = result(candidate, dataset_hash="b" * 64, total_return=0.10)
    neighbors = [
        result(candidate, dataset_hash="b" * 64, total_return=-0.10),
        result(candidate, dataset_hash="b" * 64, total_return=-0.05),
        result(candidate, dataset_hash="b" * 64, total_return=0.02),
    ]
    evidence = parameter_stability_evidence(candidate, center, neighbors, policy())
    assert evidence.passed is False


def test_policy_rejects_invalid_thresholds():
    with pytest.raises(ValueError, match="min_trades_per_slice"):
        replace(policy(), min_trades_per_slice=0)
    for field in (
        "min_profitable_slice_ratio",
        "max_drawdown",
        "max_return_degradation",
        "min_stable_neighbor_ratio",
    ):
        with pytest.raises(ValueError, match=field):
            replace(policy(), **{field: 1.1})


def test_walk_forward_rejects_empty_or_wrong_candidate_identity():
    candidate = genome()
    with pytest.raises(ValueError, match="at least one evaluation"):
        walk_forward_evidence(candidate, [], policy())

    fold = result(candidate, dataset_hash="1" * 64)
    with pytest.raises(ValueError, match="strategy_id"):
        walk_forward_evidence(candidate, [replace(fold, strategy_id="other")], policy())
    with pytest.raises(ValueError, match="genome_hash"):
        walk_forward_evidence(candidate, [replace(fold, genome_hash="g" * 64)], policy())


def test_walk_forward_rejects_mixed_engine_identity():
    candidate = genome()
    first = result(candidate, dataset_hash="1" * 64)
    with pytest.raises(ValueError, match="same engine"):
        walk_forward_evidence(candidate, [first, replace(first, engine="other")], policy())
    with pytest.raises(ValueError, match="engine_version"):
        walk_forward_evidence(candidate, [first, replace(first, engine_version="other")], policy())


def test_cost_stress_requires_same_dataset_and_handles_nonpositive_base():
    candidate = genome()
    base = result(candidate, dataset_hash="b" * 64, total_return=-0.01)
    wrong_dataset = replace(base, dataset_hash="d" * 64, fees=0.003)
    with pytest.raises(ValueError, match="same dataset_hash"):
        cost_stress_evidence(candidate, base, wrong_dataset, policy())

    improved = replace(base, total_return=0.01, fees=0.003)
    evidence = cost_stress_evidence(candidate, base, improved, policy())
    assert evidence.passed is True
    assert evidence.metrics["return_degradation"] == 0.0


def test_parameter_stability_rejects_empty_or_mismatched_neighbors():
    candidate = genome()
    center = result(candidate, dataset_hash="b" * 64, total_return=-0.01)
    with pytest.raises(ValueError, match="at least one parameter neighbor"):
        parameter_stability_evidence(candidate, center, [], policy())

    neighbor = result(candidate, dataset_hash="b" * 64, total_return=-0.01)
    with pytest.raises(ValueError, match="neighbor strategy_id"):
        parameter_stability_evidence(candidate, center, [replace(neighbor, strategy_id="other")], policy())
    with pytest.raises(ValueError, match="same dataset_hash"):
        parameter_stability_evidence(candidate, center, [replace(neighbor, dataset_hash="d" * 64)], policy())

    evidence = parameter_stability_evidence(candidate, center, [neighbor], policy())
    assert evidence.metrics["minimum_acceptable_neighbor_return"] == center.total_return
