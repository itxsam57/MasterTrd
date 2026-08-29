import numpy as np
import pandas as pd

from mastertrd.research.advanced import (
    detect_online_drift,
    evolve_continuous_parameter,
    independent_metrics,
    walk_forward_splits,
)


def test_pymoo_evolution_finds_known_continuous_optimum():
    result = evolve_continuous_parameter(
        low=-5.0,
        high=5.0,
        generations=30,
        population=32,
        seed=17,
        objective=lambda x: (x - 1.75) ** 2,
    )
    assert abs(result.best_value - 1.75) < 0.25
    assert result.best_loss < 0.07


def test_river_adwin_detects_large_distribution_shift():
    values = [0.0] * 200 + [10.0] * 200
    points = detect_online_drift(values)
    assert points
    assert points[-1] >= 200


def test_skfolio_walk_forward_has_purge_gap():
    X = np.arange(60).reshape(-1, 1)
    folds = walk_forward_splits(X, train_size=20, test_size=5, purged_size=2)
    assert len(folds) > 1
    for train, test in folds:
        assert train[-1] + 2 < test[0]
        assert len(train) == 20
        assert len(test) == 5


def test_quantstats_independent_metrics_are_finite():
    returns = pd.Series([0.01, -0.004, 0.006, 0.002, -0.003, 0.007] * 30)
    metrics = independent_metrics(returns, periods=365)
    assert np.isfinite(metrics.sharpe)
    assert np.isfinite(metrics.sortino)
    assert metrics.max_drawdown <= 0.0
