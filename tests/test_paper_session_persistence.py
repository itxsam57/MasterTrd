import json

import pytest

from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal


NANOSECOND = 1_000_000_000


def receipt() -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id="S-paper-persist",
        genome_hash="a" * 64,
        session_id="persist-session-1",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def test_paper_session_survives_restart_without_losing_event_identity(tmp_path):
    started = 10_000 * NANOSECOND
    path = tmp_path / "paper-session.json"
    store = JsonPaperSessionStore(path)
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=started)
    journal.record_closed_trade("trade-1", 0.03, timestamp_ns=started + 10 * NANOSECOND)
    journal.record_reconciliation("recon-1", ok=True, timestamp_ns=started + 20 * NANOSECOND)
    store.save(journal)

    restored = store.load()
    with pytest.raises(ValueError, match="unique"):
        restored.record_closed_trade("trade-1", 0.99, timestamp_ns=started + 30 * NANOSECOND)
    restored.record_closed_trade("trade-2", 0.02, timestamp_ns=started + 40 * NANOSECOND)
    restored.record_reconciliation("recon-2", ok=True, timestamp_ns=started + 50 * NANOSECOND)
    report = restored.finalize(ended_ns=started + 3600 * NANOSECOND)

    assert report.closed_trades == 2
    assert report.reconciliation_checks == 2
    assert report.reconciliation_errors == 0
    assert report.code_hash == "code-v1"
    assert report.completed is True


def test_corrupt_or_tampered_paper_session_state_fails_closed(tmp_path):
    path = tmp_path / "paper-session.json"
    store = JsonPaperSessionStore(path)
    path.write_text(json.dumps({"version": 1, "payload": {}, "state_hash": "bad"}), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity"):
        store.load()
