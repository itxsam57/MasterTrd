from mastertrd.contracts import StrategyState
from mastertrd.governor import evaluate_promotion


def test_governor_requires_all_evidence():
    denied = evaluate_promotion(StrategyState.BACKTESTED, StrategyState.ROBUST, {"walk_forward"})
    assert not denied.allowed
    assert denied.missing_evidence == {"cost_stress", "parameter_stability"}


def test_governor_allows_only_next_state():
    denied = evaluate_promotion(StrategyState.IDEA, StrategyState.LIVE_ELIGIBLE, {"risk_review"})
    assert not denied.allowed


def test_rejection_is_always_fail_safe():
    assert evaluate_promotion(StrategyState.IDEA, StrategyState.REJECTED, set()).allowed
