import math

import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.options_validation import (
    OptionsStressPolicy,
    OptionsStressReport,
    options_stress_evidence,
)
from mastertrd.validation import ValidationEvidence


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="OPT-1",
        family="options",
        style="swing",
        instruments=("BTC-OPTION.BINANCE",),
        timeframe="1h",
        entry={"kind": "volatility_spread"},
        exit={"kind": "risk_target"},
    )


def base_record(genome: StrategyGenome, evidence_type: str) -> ValidationEvidence:
    return ValidationEvidence(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        evidence_type=evidence_type,
        dataset_hash=f"data-{evidence_type}",
        code_hash="code-options-1",
        engine="nautilus_trader",
        engine_version="1.231.0",
        passed=True,
        metrics={"ok": 1.0},
    )


def policy() -> OptionsStressPolicy:
    return OptionsStressPolicy(
        max_abs_delta_error=0.05,
        max_abs_gamma_error=0.02,
        max_abs_vega_error=0.05,
        max_abs_theta_error=0.05,
        max_surface_price_error_ratio=0.08,
        max_surface_monotonicity_violations=0,
        max_surface_convexity_violations=0,
        min_surface_points=20,
    )


def report(genome: StrategyGenome, **changes) -> OptionsStressReport:
    values = dict(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        dataset_hash="options-surface-1",
        code_hash="code-options-1",
        engine="nautilus_trader",
        engine_version="1.231.0",
        delta_error=0.01,
        gamma_error=0.005,
        vega_error=0.02,
        theta_error=0.02,
        surface_points=30,
        max_surface_price_error_ratio=0.04,
        monotonicity_violations=0,
        convexity_violations=0,
    )
    values.update(changes)
    return OptionsStressReport(**values)


def test_options_records_close_family_specific_robust_gate():
    genome = candidate()
    greeks, surface = options_stress_evidence(genome, report(genome), policy())

    assert greeks.evidence_type == "options_greeks_validation"
    assert surface.evidence_type == "volatility_surface_stress"
    assert greeks.passed is True
    assert surface.passed is True

    records = [
        base_record(genome, "walk_forward"),
        base_record(genome, "cost_stress"),
        base_record(genome, "parameter_stability"),
        base_record(genome, "purged_cpcv"),
        base_record(genome, "monte_carlo"),
        greeks,
        surface,
    ]
    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        genome,
        records,
    )
    assert decision.allowed is True


def test_bad_greeks_do_not_hide_a_good_surface_and_vice_versa():
    genome = candidate()
    bad_greeks, good_surface = options_stress_evidence(
        genome,
        report(genome, delta_error=0.20),
        policy(),
    )
    assert bad_greeks.passed is False
    assert good_surface.passed is True

    good_greeks, bad_surface = options_stress_evidence(
        genome,
        report(genome, monotonicity_violations=1),
        policy(),
    )
    assert good_greeks.passed is True
    assert bad_surface.passed is False


def test_options_report_is_bound_to_candidate_and_nautilus_engine():
    genome = candidate()
    with pytest.raises(ValueError, match="strategy_id"):
        options_stress_evidence(genome, report(genome, strategy_id="OTHER"), policy())
    with pytest.raises(ValueError, match="genome_hash"):
        options_stress_evidence(genome, report(genome, genome_hash="wrong"), policy())
    with pytest.raises(ValueError, match="options family"):
        non_option = StrategyGenome(
            strategy_id="NOT-OPT",
            family="trend",
            style="swing",
            instruments=("BTCUSDT.BINANCE",),
            timeframe="1h",
            entry={"kind": "ema_cross"},
            exit={"kind": "cross_reverse"},
        )
        options_stress_evidence(non_option, report(non_option), policy())
    with pytest.raises(ValueError, match="nautilus_trader"):
        options_stress_evidence(genome, report(genome, engine="other_engine"), policy())


def test_options_policy_and_report_reject_impossible_values():
    with pytest.raises(ValueError):
        OptionsStressPolicy(-0.01, 0.02, 0.05, 0.05, 0.08, 0, 0, 20)
    with pytest.raises(ValueError):
        OptionsStressPolicy(0.05, 0.02, 0.05, 0.05, 1.2, 0, 0, 20)
    with pytest.raises(ValueError):
        OptionsStressPolicy(0.05, 0.02, 0.05, 0.05, 0.08, -1, 0, 20)
    with pytest.raises(ValueError):
        OptionsStressPolicy(0.05, 0.02, 0.05, 0.05, 0.08, 0, 0, 0)

    genome = candidate()
    with pytest.raises(ValueError, match="finite"):
        report(genome, delta_error=math.inf)
    with pytest.raises(ValueError, match="surface_points"):
        report(genome, surface_points=-1)
    with pytest.raises(ValueError, match="violations"):
        report(genome, convexity_violations=-1)
