from mastertrd.hft_engine import HftEngineProbeResult


def test_hft_engine_probe_result_is_a_stable_core_contract():
    result = HftEngineProbeResult(
        engine="hftbacktest",
        engine_version="2.4.4",
        event_count=4,
        best_bid=100.0,
        best_ask=100.2,
        processed=True,
    )

    assert result.engine == "hftbacktest"
    assert result.engine_version == "2.4.4"
    assert result.event_count == 4
    assert result.best_bid == 100.0
    assert result.best_ask == 100.2
    assert result.processed is True
