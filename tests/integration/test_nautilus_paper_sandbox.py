from decimal import Decimal

import pytest

import mastertrd.nautilus_paper as nautilus_paper_module
from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_paper import (
    NautilusStreamingPaperExecution,
    fixture_binance_spot_instrument,
    open_persistent_paper_session,
    probe_nautilus_sandbox_session,
)
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import PaperSessionJournal
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


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


def test_persistent_nautilus_paper_session_opens_and_resumes_same_identity(tmp_path):
    candidate = genome()
    state_path = tmp_path / "paper-session.json"
    started_ns = 10_000_000_000

    opened = open_persistent_paper_session(
        candidate,
        state_path=state_path,
        code_hash="code-v1",
        started_ns=started_ns,
        session_nonce="persistent-test",
    )
    opened.journal.record_reconciliation(
        "recon-before-restart",
        ok=True,
        timestamp_ns=started_ns + 1,
    )
    opened.store.save(opened.journal)

    resumed = open_persistent_paper_session(
        candidate,
        state_path=state_path,
        code_hash="code-v1",
        resume=True,
    )

    assert opened.resumed is False
    assert resumed.resumed is True
    assert resumed.journal.session_id == opened.journal.session_id
    assert resumed.journal.strategy_id == candidate.strategy_id
    assert resumed.journal.genome_hash == candidate.genome_hash
    assert resumed.journal.code_hash == "code-v1"
    assert resumed.journal.has_event("recon-before-restart") is True


def test_persistent_nautilus_paper_resume_fails_closed_on_code_mismatch(tmp_path):
    candidate = genome()
    state_path = tmp_path / "paper-session.json"
    open_persistent_paper_session(
        candidate,
        state_path=state_path,
        code_hash="code-v1",
        started_ns=10_000_000_000,
        session_nonce="mismatch-test",
    )

    with pytest.raises(ValueError, match="code_hash"):
        open_persistent_paper_session(
            candidate,
            state_path=state_path,
            code_hash="code-v2",
            resume=True,
        )


def test_public_binance_spot_instrument_loader_uses_exact_provider_metadata(monkeypatch):
    expected = fixture_binance_spot_instrument("ETHUSDT.BINANCE")

    class FakeProvider:
        def __init__(self):
            self.loaded = []

        async def load_async(self, instrument_id):
            self.loaded.append(instrument_id)

        def find(self, instrument_id):
            if self.loaded and instrument_id == expected.id:
                return expected
            return None

    provider = FakeProvider()
    monkeypatch.setattr(
        nautilus_paper_module,
        "_build_public_binance_spot_provider",
        lambda: provider,
        raising=False,
    )

    loaded = nautilus_paper_module.load_public_binance_spot_instrument("ETHUSDT.BINANCE")

    assert loaded is expected
    assert [instrument_id.value for instrument_id in provider.loaded] == ["ETHUSDT.BINANCE"]


def test_streaming_paper_execution_exposes_real_nautilus_reconciliation_state():
    candidate = genome()
    instrument = fixture_binance_spot_instrument("BTCUSDT.BINANCE")
    receipt = PaperStartReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        session_id="paper-state-test",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )
    journal = PaperSessionJournal(receipt, code_hash="code-v1", started_ns=1)
    execution = NautilusStreamingPaperExecution(
        candidate=candidate,
        risk_runtime=build_research_backtest_risk_runtime(),
        journal=journal,
        instrument=instrument,
    )

    try:
        state = execution.execution_state(account_id="paper:paper-state-test")
        assert state.account_id == "paper:paper-state-test"
        assert state.positions == {}
        assert state.open_order_ids == frozenset()
        assert state.balances["BTC"] == Decimal("10")
        assert state.balances["USDT"] == Decimal("100000")
    finally:
        execution.close()
