from dataclasses import replace

import pytest

from mastertrd.advanced_validation import (
    AdvancedValidationPolicy,
    monte_carlo_evidence,
    purged_cpcv_evidence,
)
from mastertrd.contracts import EvaluationResult, StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.validation import ValidationEvidence


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="ADV-1",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def result(genome: StrategyGenome, dataset_hash: str, *, total_return: float = 0.08, drawdown: float = 0.10, trades: int = 20) -> EvaluationResult:
    return EvaluationResult(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        dataset_hash=dataset_hash,
        code_hash="c" * 64,
        engine="nautilus_trader",
        engine_version="1.231.0",
        total_return=total_return,
        sharpe=1.0,
        sortino=1.2,
        max_drawdown=drawdown,
        profit_factor=1.2,
        expectancy=0.004,
        trade_count=trades,
        turnover=0.5,
        fees=0.001,
        slippage=0.001,
        scores={"execution_backtest": 1.0},
    )


def policy() -> AdvancedValidationPolicy:
    return AdvancedValidationPolicy(
        min_evaluations=4,
        min_trades_per_evaluation=5,
        min_positive_ratio=0.75,
        max_drawdown=0.25,
        min_monte_carlo_survival_ratio=0.80,
        max_monte_carlo_loss=-0.10,
    )


def base_evidence(genome: StrategyGenome, evidence_type: str) -> ValidationEvidence:
    return ValidationEvidence(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        evidence_type=evidence_type,
        dataset_hash=f"data-{evidence_type}",
        code_hash="c" * 64,
        engine="nautilus_trader",
        engine_version="1.231.0",
        passed=True,
        metrics={"ok": 1.0},
    )


def test_advanced_anti_overfit_evidence_is_required_for_robust_promotion():
    genome = candidate()
    records = [
        base_evidence(genome, "walk_forward"),
        base_evidence(genome, "cost_stress"),
        base_evidence(genome, "parameter_stability"),
    ]
    blocked = evaluate_validated_promotion(StrategyState.BACKTESTED, StrategyState.ROBUST, genome, records)
    assert blocked.allowed is False
    assert blocked.missing_evidence == frozenset({"purged_cpcv", "monte_carlo", "asset_transfer"})

    cpcv = purged_cpcv_evidence(
        genome,
        [
            result(genome, "1" * 64, total_return=0.08),
            result(genome, "2" * 64, total_return=0.05),
            result(genome, "3" * 64, total_return=0.02),
            result(genome, "4" * 64, total_return=-0.01),
        ],
        policy(),
    )
    monte = monte_carlo_evidence(
        genome,
        [
            result(genome, "a" * 64, total_return=0.04),
            result(genome, "b" * 64, total_return=0.02),
            result(genome, "d" * 64, total_return=0.01),
            result(genome, "e" * 64, total_return=0.03),
            result(genome, "f" * 64, total_return=-0.05),
        ],
        policy(),
    )
    assert cpcv.passed is True
    assert monte.passed is True
    promoted = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        genome,
        [*records, cpcv, monte, base_evidence(genome, "asset_transfer")],
    )
    assert promoted.allowed is True


def test_purged_cpcv_rejects_mixed_identity_and_weak_coverage():
    genome = candidate()
    evaluations = [result(genome, str(i) * 64) for i in range(1, 5)]
    with pytest.raises(ValueError, match="code_hash"):
        purged_cpcv_evidence(genome, [evaluations[0], replace(evaluations[1], code_hash="x" * 64), *evaluations[2:]], policy())

    weak = purged_cpcv_evidence(
        genome,
        [replace(item, total_return=-0.05) for item in evaluations],
        policy(),
    )
    assert weak.passed is False
    assert weak.metrics["positive_evaluation_ratio"] == 0.0


def test_monte_carlo_requires_enough_paths_and_rejects_tail_failure():
    genome = candidate()
    with pytest.raises(ValueError, match="min_evaluations"):
        monte_carlo_evidence(genome, [result(genome, "a" * 64)], policy())

    failed = monte_carlo_evidence(
        genome,
        [
            result(genome, "a" * 64, total_return=0.02),
            result(genome, "b" * 64, total_return=-0.20),
            result(genome, "d" * 64, total_return=-0.15),
            result(genome, "e" * 64, total_return=-0.12),
        ],
        policy(),
    )
    assert failed.passed is False
    assert failed.metrics["worst_total_return"] == -0.20


def test_advanced_policy_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        replace(policy(), min_evaluations=0)
    with pytest.raises(ValueError):
        replace(policy(), min_trades_per_evaluation=0)
    with pytest.raises(ValueError):
        replace(policy(), min_positive_ratio=1.1)
    with pytest.raises(ValueError):
        replace(policy(), max_drawdown=-0.1)
    with pytest.raises(ValueError):
        replace(policy(), min_monte_carlo_survival_ratio=1.1)
