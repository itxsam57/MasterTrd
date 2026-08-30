from mastertrd.genome import StrategyGenome
from mastertrd.strategy_families import DataLevel
from mastertrd.validation import validation_profile


def make(family):
    return StrategyGenome(
        strategy_id=f"S-{family}", family=family, style="auto",
        instruments=("BTCUSDT",), timeframe="1m",
        entry={"signal": True}, exit={"stop": True},
    )


def test_scalping_requires_promotion_grade_historical_l2_evidence():
    profile = validation_profile(make("scalping"))
    assert profile.minimum_data_level is DataLevel.TICK
    assert "hft_real_l2" in profile.required_evidence
    assert "hft_queue_model" not in profile.required_evidence
    assert "hft_order_latency_stress" not in profile.required_evidence


def test_swing_does_not_require_hft_evidence():
    profile = validation_profile(make("swing"))
    assert "hft_real_l2" not in profile.required_evidence


def test_options_add_specialist_options_evidence():
    profile = validation_profile(make("options"))
    assert "options_greeks_validation" in profile.required_evidence
    assert "volatility_surface_stress" in profile.required_evidence
