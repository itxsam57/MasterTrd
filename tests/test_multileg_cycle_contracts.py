import ast
from inspect import getsource, signature
from textwrap import dedent

import mastertrd.research_brain as research_brain
from mastertrd.hidden_cycle import run_generated_hidden_cycle
from mastertrd.robustness_cycle import run_generated_robustness_cycle


def _call_keyword_sets(function_name: str) -> tuple[frozenset[str], ...]:
    tree = ast.parse(dedent(getsource(research_brain.run_research_brain)))
    calls: list[frozenset[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != function_name:
            continue
        calls.append(frozenset(keyword.arg for keyword in node.keywords if keyword.arg is not None))
    return tuple(calls)


def test_robustness_cycle_uses_generalized_instrument_and_data_mappings():
    parameters = signature(run_generated_robustness_cycle).parameters

    assert "instruments" in parameters
    assert "data_by_instrument" in parameters
    assert "instrument" not in parameters
    assert "data" not in parameters
    assert "legacy_inputs" not in parameters


def test_hidden_cycle_uses_generalized_instrument_and_data_mappings():
    parameters = signature(run_generated_hidden_cycle).parameters

    assert "instruments" in parameters
    assert "hidden_data_by_instrument" in parameters
    assert "instrument" not in parameters
    assert "hidden_data" not in parameters
    assert "legacy_inputs" not in parameters


def test_research_brain_calls_robustness_cycle_through_generalized_contract():
    calls = _call_keyword_sets("run_generated_robustness_cycle")

    assert calls
    for keywords in calls:
        assert {"instruments", "data_by_instrument"} <= keywords
        assert "instrument" not in keywords
        assert "data" not in keywords


def test_research_brain_calls_hidden_cycle_through_generalized_contract():
    calls = _call_keyword_sets("run_generated_hidden_cycle")

    assert calls
    for keywords in calls:
        assert {"instruments", "hidden_data_by_instrument"} <= keywords
        assert "instrument" not in keywords
        assert "hidden_data" not in keywords
