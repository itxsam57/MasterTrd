from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_paper import probe_nautilus_sandbox_session


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-paper-trend",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def test_stable_nautilus_sandbox_can_initialize_connect_and_disconnect_without_credentials():
    candidate = genome()
    receipt = probe_nautilus_sandbox_session(candidate)

    assert receipt.strategy_id == candidate.strategy_id
    assert receipt.genome_hash == candidate.genome_hash
    assert receipt.engine == "nautilus_trader"
    assert receipt.engine_version == "1.231.0"
    assert receipt.venue == "SANDBOX"
    assert receipt.connected is True
    assert receipt.session_id
