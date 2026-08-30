import numpy as np

from mastertrd.research.volatility import forecast_volatility


def test_forecast_volatility_returns_positive_hashed_horizon():
    rng = np.random.default_rng(21)
    scale = np.r_[np.full(250, 0.006), np.full(250, 0.02)]
    returns = rng.normal(0.0, scale)

    evidence = forecast_volatility(returns, horizon=3)

    assert len(evidence.dataset_hash) == 64
    assert evidence.horizon == 3
    assert len(evidence.forecast) == 3
    assert all(np.isfinite(value) and value > 0.0 for value in evidence.forecast)
