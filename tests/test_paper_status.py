from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import PaperSessionJournal
from mastertrd.reconciliation import ExecutionState


NANOSECOND = 1_000_000_000


def _receipt() -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id="S-paper-status",
        genome_hash="a" * 64,
        session_id="paper-status-session",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def test_paper_status_snapshot_is_read_only_and_reports_current_evidence():
    started = 1_000 * NANOSECOND
    journal = PaperSessionJournal(_receipt(), code_hash="code-status", started_ns=started)
    journal.record_market_event("bar-1", timestamp_ns=started + 15 * NANOSECOND)
    journal.record_closed_trade("trade-1", 0.10, timestamp_ns=started + 20 * NANOSECOND)
    journal.record_closed_trade("trade-2", -0.05, timestamp_ns=started + 30 * NANOSECOND)
    journal.record_reconciliation("recon-1", ok=True, timestamp_ns=started + 35 * NANOSECOND)
    journal.record_reconciliation("recon-2", ok=False, timestamp_ns=started + 40 * NANOSECOND)
    journal.record_execution_state(
        ExecutionState(
            account_id="PAPER-ACCOUNT",
            positions={"ETHUSDT.BINANCE": "0.01000"},
            open_order_ids=frozenset({"order-1"}),
            balances={"USDT": "1000"},
        ),
        timestamp_ns=started + 45 * NANOSECOND,
    )

    module = importlib.import_module("mastertrd.paper_status")
    payload = module.paper_status_payload(journal, observed_ns=started + 60 * NANOSECOND)

    assert payload == {
        "schema_version": 1,
        "strategy_id": "S-paper-status",
        "genome_hash": "a" * 64,
        "code_hash": "code-status",
        "session_id": "paper-status-session",
        "duration_seconds": 60,
        "market_events": 1,
        "closed_trades": 2,
        "total_return": pytest.approx(0.045),
        "max_drawdown": pytest.approx(0.05),
        "reconciliation_checks": 2,
        "reconciliation_errors": 1,
        "position_count": 1,
        "open_order_count": 1,
        "latest_timestamp_ns": started + 45 * NANOSECOND,
        "finalized": False,
    }
    assert journal.finalized_report is None


def test_paper_status_accepts_pre_telemetry_legacy_journal_shape():
    started = 2_000 * NANOSECOND
    current = PaperSessionJournal(_receipt(), code_hash="legacy-code", started_ns=started)
    current.record_market_event("bar-legacy", timestamp_ns=started + NANOSECOND)
    current.record_reconciliation("recon-legacy", ok=True, timestamp_ns=started + 2 * NANOSECOND)

    legacy = SimpleNamespace(
        started_ns=current.started_ns,
        latest_timestamp_ns=current.latest_timestamp_ns,
        strategy_id=current.strategy_id,
        genome_hash=current.genome_hash,
        code_hash=current.code_hash,
        session_id=current.session_id,
        _events=current._events,
        execution_state_checkpoint=current.execution_state_checkpoint,
        finalized_report=current.finalized_report,
    )

    module = importlib.import_module("mastertrd.paper_status")
    payload = module.paper_status_payload(legacy, observed_ns=started + 3 * NANOSECOND)

    assert payload["strategy_id"] == "S-paper-status"
    assert payload["code_hash"] == "legacy-code"
    assert payload["market_events"] == 1
    assert payload["reconciliation_errors"] == 0
    assert "bars_seen" not in payload
    assert "warmup_remaining" not in payload


def test_paper_status_workflow_is_read_only_and_publishes_safe_artifact():
    path = Path(".github/workflows/paper-status.yml")
    assert path.exists()
    workflow = path.read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "*/5 * * * *" in workflow
    assert "workflow_dispatch:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "src/mastertrd/paper_status.py" in workflow
    assert "src/mastertrd/paper_diagnostics.py" in workflow
    assert "environment: oracle" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "paper-status.json" in workflow
    assert "systemctl show" in workflow
    assert "journalctl -u mastertrd.service" in workflow
    assert "ExecMainCode" in workflow
    assert "ExecMainStatus" in workflow
    assert "PAPER_STATUS_DIAGNOSTICS_PATH" in workflow

    forbidden = (
        "systemctl restart",
        "systemctl stop",
        "LIVE_TRADING_ENABLED=true",
        "MASTERTRD_MODE=LIVE",
        "sed -i",
        "tee -a /etc/mastertrd",
        "journalctl -u mastertrd.service > artifacts",
    )
    for token in forbidden:
        assert token not in workflow
