import pytest

from mastertrd.strategy_families import DataLevel, family_spec


def test_market_making_requires_l2_and_hft_validation():
    spec = family_spec("market_making")
    assert spec.min_data_level is DataLevel.L2
    assert spec.requires_hft_validation


def test_swing_can_use_bar_data_without_hft_gate():
    spec = family_spec("swing")
    assert spec.min_data_level is DataLevel.BAR
    assert not spec.requires_hft_validation


def test_unknown_family_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        family_spec("magic_profit")
