import numpy as np

from mastertrd.research.statistics import cointegration_evidence


def test_cointegration_evidence_is_hashed_and_significant_for_shared_trend():
    rng = np.random.default_rng(12)
    left = np.cumsum(rng.normal(size=400))
    right = 2.2 * left + rng.normal(scale=0.35, size=400)

    evidence = cointegration_evidence(left, right, max_pvalue=0.05)

    assert len(evidence.dataset_hash) == 64
    assert evidence.observations == 400
    assert 0.0 <= evidence.pvalue <= 1.0
    assert evidence.passed is True
    assert evidence.pvalue <= evidence.max_pvalue
