import sys
from types import SimpleNamespace

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


def test_discover_regimes_bounds_large_pelt_candidate_grid(monkeypatch):
    observations = 17_567
    calls: dict[str, int] = {}

    class FakePelt:
        def __init__(self, *, model: str, min_size: int, jump: int):
            assert model == "l2"
            assert min_size == 5
            calls["jump"] = jump

        def fit(self, signal):
            calls["observations"] = len(signal)
            return self

        def predict(self, *, pen: float):
            assert pen == 5.0
            return [calls["observations"]]

    monkeypatch.setitem(sys.modules, "ruptures", SimpleNamespace(Pelt=FakePelt))

    evidence = discover_regimes(np.zeros(observations), min_size=5, penalty=5.0)

    assert calls["observations"] == observations
    assert calls["jump"] == 5
    assert evidence.jump == 5
