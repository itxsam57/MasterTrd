import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.multi_leg_validation import (
    MultiLegStressPolicy,
    MultiLegStressReport,
    multi_leg_execution_stress_evidence,
)
from mastertrd.validation import ValidationEvidence


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="PAIR-1",
        family="stat_arb",
        style="intraday",
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        timeframe="1m",
        entry={"kind": "zscore_pair", "threshold": 2.0},
        exit={"kind": "mean_revert", "threshold": 0.5},
        allow_short=True,
    )


def base_record(genome: StrategyGenome, evidence_type: str) -> ValidationEvidence:
    return ValidationEvidence(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        evidence_type=evidence_type,
        dataset_hash=f"data-{evidence_type}",
        code_hash="code-1",
        engine="nautilus_trader",
        engine_version="1.231.0",
        passed=True,
        metrics={"ok": 1.0},
    )


def policy() -> MultiLegStressPolicy:
    return MultiLegStressPolicy(
        min_completed_cycles=20,
        max_leg_fill_skew=0.10,
        max_residual_exposure_ratio=0.05,
        max_slippage_bps=15.0,
    )


def report(genome: StrategyGenome, **changes) -> MultiLegStressReport:
    values = dict(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        dataset_hash="pair-stress-1",
        code_hash="code-1",
        engine="nautilus_trader",
        engine_version="1.231.0",
        expected_legs=2,
        completed_cycles=25,
        leg_fill_counts=(25, 24),
        residual_exposure_ratio=0.02,
        slippage_bps=8.0,
    )
    values.update(changes)
    return MultiLegStressReport(**values)


def test_multi_leg_stress_closes_family_specific_robust_gate():
    genome = candidate()
    stress = multi_leg_execution_stress_evidence(genome, report(genome), policy())
    assert stress.evidence_type == "multi_leg_execution_stress"
    assert stress.passed is True
    assert stress.metrics["leg_count"] == 2.0
    assert stress.metrics["leg_fill_skew"] <= 0.10

    records = [
        base_record(genome, "walk_forward"),
        base_record(genome, "cost_stress"),
        base_record(genome, "parameter_stability"),
        stress,
    ]
    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        genome,
        records,
    )
    assert decision.allowed is True


def test_leg_imbalance_or_residual_exposure_fails_stress():
    genome = candidate()
    imbalanced = multi_leg_execution_stress_evidence(
        genome,
        report(genome, leg_fill_counts=(25, 15)),
        policy(),
    )
    assert imbalanced.passed is False

    residual = multi_leg_execution_stress_evidence(
        genome,
        report(genome, residual_exposure_ratio=0.20),
        policy(),
    )
    assert residual.passed is False


def test_report_must_match_candidate_and_actual_leg_count():
    genome = candidate()
    with pytest.raises(ValueError, match="strategy_id"):
        multi_leg_execution_stress_evidence(
            genome,
            report(genome, strategy_id="OTHER"),
            policy(),
        )
    with pytest.raises(ValueError, match="expected_legs"):
        multi_leg_execution_stress_evidence(
            genome,
            report(genome, expected_legs=3, leg_fill_counts=(25, 25, 25)),
            policy(),
        )


def test_multi_leg_policy_rejects_impossible_thresholds():
    with pytest.raises(ValueError):
        MultiLegStressPolicy(0, 0.10, 0.05, 15.0)
    with pytest.raises(ValueError):
        MultiLegStressPolicy(20, 1.10, 0.05, 15.0)
    with pytest.raises(ValueError):
        MultiLegStressPolicy(20, 0.10, -0.01, 15.0)
