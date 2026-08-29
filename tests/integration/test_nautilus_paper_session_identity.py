from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_paper import probe_nautilus_sandbox_session


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-paper-session-id",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def test_sandbox_probe_session_identity_is_unique_per_explicit_forward_session():
    candidate = genome()

    first = probe_nautilus_sandbox_session(candidate, session_nonce="2026-08-29T13:00:00Z")
    repeated = probe_nautilus_sandbox_session(candidate, session_nonce="2026-08-29T13:00:00Z")
    second = probe_nautilus_sandbox_session(candidate, session_nonce="2026-08-29T14:00:00Z")

    assert first.session_id == repeated.session_id
    assert first.receipt_hash == repeated.receipt_hash
    assert first.session_id != second.session_id
    assert first.receipt_hash != second.receipt_hash
