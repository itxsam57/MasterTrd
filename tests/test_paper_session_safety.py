import json

import pytest

from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal


NS = 1_000_000_000


def receipt(**changes) -> PaperStartReceipt:
    values = dict(
        strategy_id="S-safe",
        genome_hash="b" * 64,
        session_id="safe-session",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )
    values.update(changes)
    return PaperStartReceipt(**values)


def test_journal_rejects_invalid_session_identity_and_start_state():
    with pytest.raises(ValueError, match="connected"):
        PaperSessionJournal(receipt(connected=False), code_hash="code", started_ns=0)
    with pytest.raises(ValueError, match="Nautilus SANDBOX"):
        PaperSessionJournal(receipt(venue="OTHER"), code_hash="code", started_ns=0)
    with pytest.raises(ValueError, match="code_hash"):
        PaperSessionJournal(receipt(), code_hash="", started_ns=0)
    with pytest.raises(ValueError, match="started_ns"):
        PaperSessionJournal(receipt(), code_hash="code", started_ns=-1)


def test_journal_rejects_bad_events_and_post_finalize_mutation():
    started = 100 * NS
    journal = PaperSessionJournal(receipt(), code_hash="code", started_ns=started)
    with pytest.raises(ValueError, match="below -1"):
        journal.record_closed_trade("bad-return", -1.01, timestamp_ns=started)
    with pytest.raises(ValueError, match="event_id"):
        journal.record_reconciliation("", ok=True, timestamp_ns=started)
    with pytest.raises(ValueError, match="session start"):
        journal.record_reconciliation("early", ok=True, timestamp_ns=started - 1)

    journal.record_reconciliation("recon", ok=True, timestamp_ns=started + 2 * NS)
    with pytest.raises(ValueError, match="timestamp order"):
        journal.record_closed_trade("late-order", 0.01, timestamp_ns=started + NS)
    with pytest.raises(ValueError, match="session start"):
        journal.finalize(ended_ns=started - 1)
    with pytest.raises(ValueError, match="latest session event"):
        journal.finalize(ended_ns=started + NS)

    journal.finalize(ended_ns=started + 3 * NS)
    with pytest.raises(ValueError, match="already finalized"):
        journal.record_reconciliation("after-final", ok=True, timestamp_ns=started + 4 * NS)
    with pytest.raises(ValueError, match="already finalized"):
        journal.finalize(ended_ns=started + 5 * NS)


def test_store_rejects_bad_json_shape_version_and_invalid_payload(tmp_path):
    path = tmp_path / "state.json"
    store = JsonPaperSessionStore(path)

    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        store.load()

    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        store.load()

    payload = {"receipt": {}, "code_hash": "code", "started_ns": 0, "events": [], "finalized": False}
    state_hash = store._hash_payload(payload)
    path.write_text(json.dumps({"version": 99, "payload": payload, "state_hash": state_hash}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        store.load()

    path.write_text(json.dumps({"version": 1, "payload": payload, "state_hash": state_hash}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        store.load()


def test_store_rejects_invalid_event_kind_and_non_boolean_reconciliation(tmp_path):
    path = tmp_path / "state.json"
    store = JsonPaperSessionStore(path)
    base = {
        "receipt": {
            "strategy_id": "S-safe",
            "genome_hash": "b" * 64,
            "session_id": "safe-session",
            "venue": "SANDBOX",
            "engine": "nautilus_trader",
            "engine_version": "1.231.0",
            "connected": True,
        },
        "code_hash": "code",
        "started_ns": 0,
        "finalized": False,
    }

    for event in (
        {"kind": "unknown", "event_id": "x", "timestamp_ns": 1, "value": True},
        {"kind": "reconciliation", "event_id": "x", "timestamp_ns": 1, "value": 1},
    ):
        payload = {**base, "events": [event]}
        path.write_text(
            json.dumps({"version": 1, "payload": payload, "state_hash": store._hash_payload(payload)}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="invalid"):
            store.load()
