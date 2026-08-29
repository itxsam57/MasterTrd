import numpy as np
import pandas as pd

from mastertrd.research.market_stats import cointegration_pvalue, detect_change_points, forecast_volatility
from mastertrd.research.optimize import optimize_integer_parameter
from mastertrd.research.screen import moving_average_screen


def synthetic_prices(n=240):
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0005, 0.01, n)
    return pd.Series(100 * np.exp(np.cumsum(returns)))


def test_vectorbt_screen_returns_canonical_metrics():
    prices = synthetic_prices()
    result = moving_average_screen(prices, fast=8, slow=30, fees=0.001)
    assert result.engine == "vectorbt"
    assert result.trade_count >= 0
    assert np.isfinite(result.total_return)
    assert np.isfinite(result.max_drawdown)


def test_optuna_finds_integer_near_known_optimum():
    result = optimize_integer_parameter(
        name="window",
        low=2,
        high=30,
        trials=40,
        seed=11,
        objective=lambda x: -float((x - 17) ** 2),
    )
    assert abs(result.best_value - 17) <= 1
    assert result.trials_completed == 40


def test_regime_detector_finds_structural_break():
    series = np.r_[np.zeros(80), np.ones(80) * 5, np.ones(80) * -3]
    breaks = detect_change_points(series, penalty=5)
    assert any(abs(point - 80) <= 5 for point in breaks)
    assert any(abs(point - 160) <= 5 for point in breaks)


def test_cointegration_detects_shared_stochastic_trend():
    rng = np.random.default_rng(12)
    x = np.cumsum(rng.normal(size=400))
    y = 2.5 * x + rng.normal(scale=0.4, size=400)
    assert cointegration_pvalue(x, y) < 0.05


def test_garch_volatility_forecast_is_positive_and_finite():
    rng = np.random.default_rng(21)
    returns = rng.normal(0, 0.01, 500)
    vol = forecast_volatility(returns)
    assert np.isfinite(vol)
    assert vol > 0
