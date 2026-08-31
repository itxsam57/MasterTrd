from inspect import signature

from mastertrd.hidden_cycle import run_generated_hidden_cycle
from mastertrd.robustness_cycle import run_generated_robustness_cycle


def test_robustness_cycle_uses_generalized_instrument_and_data_mappings():
    parameters = signature(run_generated_robustness_cycle).parameters

    assert "instruments" in parameters
    assert "data_by_instrument" in parameters
    assert "instrument" not in parameters
    assert "data" not in parameters


def test_hidden_cycle_uses_generalized_instrument_and_data_mappings():
    parameters = signature(run_generated_hidden_cycle).parameters

    assert "instruments" in parameters
    assert "hidden_data_by_instrument" in parameters
    assert "instrument" not in parameters
    assert "hidden_data" not in parameters
