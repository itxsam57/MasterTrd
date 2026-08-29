import numpy as np

from mastertrd.hft_engine import probe_hftbacktest_engine


def test_real_hftbacktest_engine_processes_l2_events():
    result = probe_hftbacktest_engine()
    assert result.engine == "hftbacktest"
    assert result.engine_version
    assert result.event_count >= 4
    assert result.best_bid == 100.0
    assert result.best_ask == 100.2
    assert result.processed is True
