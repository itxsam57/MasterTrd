from math import isclose

import pytest

from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import PaperSessionJournal


NANOSECOND = 1_000_000_000


def receipt() -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id="S-paper-journal",
        genome_hash="g" * 64,
        session_id="session-1",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def test_forward_report_metrics_are_derived_from_append_only_session_events():
    started = 1_000 * NANOSECOND
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=started)

    journal.record_closed_trade("trade-1", 0.10, timestamp_ns=started + 60 * NANOSECOND)
    journal.record_closed_trade("trade-2", -0.05, timestamp_ns=started + 120 * NANOSECOND)
    journal.record_reconciliation("recon-1", ok=True, timestamp_ns=started + 150 * NANOSECOND)
    report = journal.finalize(ended_ns=started + 3600 * NANOSECOND)

    assert report.duration_seconds == 3600
    assert report.closed_trades == 2
    assert isclose(report.total_return, 0.045, rel_tol=0.0, abs_tol=1e-12)
    assert isclose(report.max_drawdown, 0.05, rel_tol=0.0, abs_tol=1e-12)
    assert report.reconciliation_errors == 0
    assert report.reconciliation_checks == 1
    assert report.code_hash == "code-v1"
    assert report.provenance_verified is True
    assert len(report.session_event_hash) == 64
    assert report.completed is True
    assert report.data_healthy is True
    assert report.missing_closed_bars == 0


def test_forward_report_carries_integrity_covered_data_health():
    started = 1_500 * NANOSECOND
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=started)
    journal.record_strategy_telemetry(
        {
            "bars_seen": 10,
            "bars_required": 8,
            "warmup_remaining": 0,
            "last_signal": "FLAT",
            "last_signal_reason": "no_signal",
            "orders_attempted": 0,
            "orders_rejected": 0,
            "last_risk_rejection": None,
            "data_healthy": False,
            "missing_closed_bars": 1,
        },
        timestamp_ns=started + 10 * NANOSECOND,
    )
    journal.record_reconciliation("recon-health", ok=True, timestamp_ns=started + 20 * NANOSECOND)

    report = journal.finalize(ended_ns=started + 60 * NANOSECOND)

    assert report.data_healthy is False
    assert report.missing_closed_bars == 1


def test_duplicate_trade_or_out_of_window_event_cannot_inflate_paper_report():
    started = 2_000 * NANOSECOND
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=started)
    journal.record_closed_trade("trade-1", 0.01, timestamp_ns=started + NANOSECOND)

    with pytest.raises(ValueError, match="unique"):
        journal.record_closed_trade("trade-1", 0.02, timestamp_ns=started + 2 * NANOSECOND)
    with pytest.raises(ValueError, match="session start"):
        journal.record_reconciliation("recon-early", ok=True, timestamp_ns=started - 1)


def test_session_without_reconciliation_is_not_completed():
    started = 3_000 * NANOSECOND
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=started)
    journal.record_closed_trade("trade-1", 0.01, timestamp_ns=started + NANOSECOND)

    report = journal.finalize(ended_ns=started + 60 * NANOSECOND)

    assert report.completed is False
    assert report.reconciliation_checks == 0
