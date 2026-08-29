from mastertrd.contracts import StrategyState
from mastertrd.governor import evaluate_promotion


def test_governor_requires_all_evidence():
    denied = evaluate_promotion(StrategyState.BACKTESTED, StrategyState.ROBUST, {"walk_forward"})
    assert not denied.allowed
    assert denied.missing_evidence == {
        "cost_stress",
        "parameter_stability",
        "purged_cpcv",
        "monte_carlo",
        "asset_transfer",
    }


def test_governor_still_denies_robust_without_asset_transfer_after_other_global_gates_pass():
    denied = evaluate_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        {
            "walk_forward",
            "cost_stress",
            "parameter_stability",
            "purged_cpcv",
            "monte_carlo",
        },
    )
    assert denied.allowed is False
    assert denied.missing_evidence == {"asset_transfer"}


def test_governor_allows_only_next_state():
    denied = evaluate_promotion(StrategyState.IDEA, StrategyState.LIVE_ELIGIBLE, {"risk_review"})
    assert not denied.allowed


def test_rejection_is_always_fail_safe():
    assert evaluate_promotion(StrategyState.IDEA, StrategyState.REJECTED, set()).allowed
