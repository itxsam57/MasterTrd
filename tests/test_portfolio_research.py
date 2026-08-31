import numpy as np
import pandas as pd

from mastertrd.research.portfolio import portfolio_stress


def test_portfolio_stress_uses_purged_walk_forward_and_hashes_dataset():
    rng = np.random.default_rng(44)
    frame = pd.DataFrame(
        {
            "btc": rng.normal(0.0004, 0.012, 120),
            "eth": rng.normal(0.0005, 0.016, 120),
            "sol": rng.normal(0.0003, 0.022, 120),
        }
    )

    evidence = portfolio_stress(frame, train_size=40, test_size=10, purged_size=2)

    assert len(evidence.dataset_hash) == 64
    assert evidence.fold_count >= 2
    assert np.isfinite(evidence.worst_fold_return)
    assert np.isfinite(evidence.mean_fold_return)
    assert evidence.assets == ("btc", "eth", "sol")
