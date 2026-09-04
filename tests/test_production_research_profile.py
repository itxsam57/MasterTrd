from pathlib import Path

import mastertrd.research_job as research_job


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "autonomous-research.yml"


def _profile(name: str):
    profile_type = getattr(research_job, "ResearchProfile", None)
    assert profile_type is not None, "research jobs need explicit smoke/production profiles"
    return profile_type(name)


def _config(profile_name: str):
    factory = getattr(research_job, "research_brain_config_for_run", None)
    assert factory is not None, "research jobs need one audited config factory"
    plan = research_job.research_job_plan_for_recipe("atr-breakout-slow")
    return factory(
        plan=plan,
        family="volatility",
        seed=42,
        recipe_id="atr-breakout-slow",
        profile=_profile(profile_name),
    )


def test_smoke_profile_preserves_fast_pipeline_contract():
    config = _config("smoke")

    assert config.screening_min_return == -1.0
    assert config.optimization_trials == 2
    assert config.evolution_generations == 1
    assert config.evolution_population == 4
    assert config.validation_window == 50
    assert config.fees == 0.0
    assert config.slippage == 0.0
    assert config.robustness_policy.min_trades_per_slice == 1
    assert config.robustness_policy.max_drawdown == 0.99


def test_production_profile_cannot_use_smoke_grade_search_costs_or_gates():
    config = _config("production")

    assert config.screening_min_return >= 0.0
    assert config.optimization_trials >= 24
    assert config.evolution_generations >= 8
    assert config.evolution_population >= 16
    assert config.validation_window >= 50

    assert config.fees > 0.0
    assert config.slippage > 0.0
    assert config.stressed_fees > config.fees
    assert config.stressed_slippage > config.slippage

    robustness = config.robustness_policy
    assert robustness.min_trades_per_slice >= 5
    assert robustness.min_profitable_slice_ratio >= 0.50
    assert robustness.max_drawdown <= 0.25
    assert robustness.min_stressed_return >= 0.0
    assert robustness.max_return_degradation <= 0.50
    assert robustness.min_stable_neighbor_ratio >= 0.50

    advanced = config.advanced_policy
    # ResearchBrain currently materializes one CPCV case and one Monte-Carlo case.
    # Production therefore requires that one case to pass strongly rather than
    # pretending that multiple independent evaluations already exist.
    assert advanced.min_evaluations == 1
    assert advanced.min_trades_per_evaluation >= 5
    assert advanced.min_positive_ratio == 1.0
    assert advanced.max_drawdown <= 0.25
    assert advanced.min_monte_carlo_survival_ratio == 1.0
    assert advanced.max_monte_carlo_loss >= -0.10

    transfer = config.asset_transfer_policy
    assert transfer.min_transfer_assets == 1
    assert transfer.min_trades_per_asset >= 5
    assert transfer.min_pass_ratio == 1.0
    assert transfer.min_total_return >= 0.0
    assert transfer.max_drawdown <= 0.25

    hidden = config.hidden_policy
    assert hidden.min_trades_per_evaluation >= 5
    assert hidden.min_total_return >= 0.0
    assert hidden.max_drawdown <= 0.25
    assert hidden.min_regime_pass_ratio >= 0.67


def test_autonomous_research_workflow_explicitly_uses_production_profile():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "MASTERTRD_RESEARCH_PROFILE: production" in text
