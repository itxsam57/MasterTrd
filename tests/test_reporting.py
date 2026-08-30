import numpy as np

from mastertrd.research.reporting import build_independent_report


def test_independent_report_is_finite_and_dataset_linked():
    returns = np.asarray([0.01, -0.004, 0.006, 0.002, -0.003, 0.007] * 40, dtype=float)

    report = build_independent_report(returns, periods=365)

    assert len(report.dataset_hash) == 64
    assert report.observations == len(returns)
    assert np.isfinite(report.sharpe)
    assert np.isfinite(report.sortino)
    assert np.isfinite(report.max_drawdown)
    assert np.isfinite(report.compounded_return)
