import math
import pytest

from mastertrd.contracts import EvaluationResult


def make_result(**changes):
    values = dict(
        strategy_id="S-1", genome_hash="g", dataset_hash="d", code_hash="c",
        engine="nautilus", engine_version="1", total_return=0.1, sharpe=1.2,
        sortino=1.5, max_drawdown=0.08, profit_factor=1.3, expectancy=0.01,
        trade_count=20, turnover=1.0, fees=2.0, slippage=1.0,
        scores={"hidden": 0.8},
    )
    values.update(changes)
    return EvaluationResult(**values)


def test_evaluation_result_accepts_finite_metrics():
    assert make_result().trade_count == 20


def test_evaluation_result_rejects_non_finite_metric():
    with pytest.raises(ValueError, match="finite"):
        make_result(sharpe=math.inf)


def test_evaluation_result_rejects_negative_costs():
    with pytest.raises(ValueError, match="negative"):
        make_result(fees=-1)
