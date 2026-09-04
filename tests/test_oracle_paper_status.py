from __future__ import annotations

import json

import pytest

from mastertrd.oracle_paper_status import oracle_paper_status_payload
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal


NANOSECOND = 1_000_000_000


def _journal(*, strategy_id: str, genome_hash: str, code_hash: str, session_id: str) -> PaperSessionJournal:
    receipt = PaperStartReceipt(
        strategy_id=strategy_id,
        genome_hash=genome_hash,
        session_id=session_id,
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )
    journal = PaperSessionJournal(receipt, code_hash=code_hash, started_ns=1_000 * NANOSECOND)
    journal.record_market_event(f"bar-{strategy_id}", timestamp_ns=1_010 * NANOSECOND)
    journal.record_reconciliation(f"recon-{strategy_id}", ok=True, timestamp_ns=1_011 * NANOSECOND)
    return journal


def _write_matrix(root, *, code_hash: str = "code-matrix"):
    rows = [
        {"instance": "g-aaaaaaaaaaaaaaaa", "strategy_id": "S-one", "genome_hash": "a" * 64, "timeframe": "1m", "code_hash": code_hash},
        {"instance": "g-bbbbbbbbbbbbbbbb", "strategy_id": "S-two", "genome_hash": "b" * 64, "timeframe": "5m", "code_hash": code_hash},
    ]
    root.mkdir(parents=True)
    (root / "deployment-index.json").write_text(
        json.dumps({"code_hash": code_hash, "lock_hash": "lock", "candidates": rows}),
        encoding="utf-8",
    )
    for row in rows:
        strategy_root = root / row["genome_hash"]
        strategy_root.mkdir()
        journal = _journal(
            strategy_id=row["strategy_id"],
            genome_hash=row["genome_hash"],
            code_hash=code_hash,
            session_id=f"session-{row['strategy_id']}",
        )
        if row["strategy_id"] == "S-one":
            journal.record_closed_trade("trade-one", 0.02, timestamp_ns=1_012 * NANOSECOND)
        JsonPaperSessionStore(strategy_root / "paper-session.json").save(journal)
    return rows


def test_oracle_paper_status_aggregates_isolated_strategy_sessions(tmp_path):
    root = tmp_path / "code-matrix"
    _write_matrix(root)

    payload = oracle_paper_status_payload(root, observed_ns=1_020 * NANOSECOND)

    assert payload["code_hash"] == "code-matrix"
    assert payload["strategy_count"] == 2
    assert [row["instance"] for row in payload["strategies"]] == [
        "g-aaaaaaaaaaaaaaaa",
        "g-bbbbbbbbbbbbbbbb",
    ]
    first, second = payload["strategies"]
    assert first["strategy_id"] == "S-one"
    assert first["closed_trades"] == 1
    assert first["reconciliation_errors"] == 0
    assert first["timeframe"] == "1m"
    assert second["strategy_id"] == "S-two"
    assert second["closed_trades"] == 0
    assert second["timeframe"] == "5m"


def test_oracle_paper_status_fails_closed_on_index_or_session_identity_mismatch(tmp_path):
    root = tmp_path / "code-matrix"
    rows = _write_matrix(root)

    bad_index = json.loads((root / "deployment-index.json").read_text(encoding="utf-8"))
    bad_index["candidates"][0]["strategy_id"] = "S-wrong"
    (root / "deployment-index.json").write_text(json.dumps(bad_index), encoding="utf-8")
    with pytest.raises(RuntimeError, match="identity"):
        oracle_paper_status_payload(root, observed_ns=1_020 * NANOSECOND)

    bad_index["candidates"][0]["strategy_id"] = rows[0]["strategy_id"]
    bad_index["code_hash"] = "wrong-code"
    (root / "deployment-index.json").write_text(json.dumps(bad_index), encoding="utf-8")
    with pytest.raises(RuntimeError, match="code"):
        oracle_paper_status_payload(root, observed_ns=1_020 * NANOSECOND)
