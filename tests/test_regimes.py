import numpy as np

from mastertrd.research.regimes import discover_regimes


def test_discover_regimes_returns_hashed_finite_evidence():
    values = np.r_[np.zeros(80), np.ones(80) * 4.0, np.ones(80) * -2.0]
    evidence = discover_regimes(values, min_size=5, penalty=5.0)

    assert evidence.dataset_hash and len(evidence.dataset_hash) == 64
    assert evidence.observations == len(values)
    assert evidence.change_points
    assert all(0 < point < len(values) for point in evidence.change_points)
    assert np.isfinite(evidence.penalty)
