from mastertrd.paper_archive import JsonPaperReportArchive
from mastertrd.paper_cycle import finalize_forward_paper_session
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal


NANOSECOND = 1_000_000_000


def _receipt() -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id="S-forward-persist",
        genome_hash="f" * 64,
        session_id="forward-session-1",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def test_finalized_forward_session_reloads_to_same_report_and_archives_exactly_once(tmp_path):
    started_ns = 10_000 * NANOSECOND
    ended_ns = started_ns + 3_600 * NANOSECOND
    store = JsonPaperSessionStore(tmp_path / "paper-session.json")
    archive = JsonPaperReportArchive(tmp_path / "paper-reports.json")
    journal = PaperSessionJournal(_receipt(), code_hash="code-v1", started_ns=started_ns)
    journal.record_market_event("bar-1", timestamp_ns=started_ns + 10 * NANOSECOND)
    journal.record_closed_trade("trade-1", 0.03, timestamp_ns=started_ns + 20 * NANOSECOND)
    journal.record_reconciliation("recon-1", ok=True, timestamp_ns=started_ns + 30 * NANOSECOND)
    store.save(journal)

    first = finalize_forward_paper_session(
        journal=journal,
        session_store=store,
        archive=archive,
        ended_ns=ended_ns,
    )

    assert first.provenance_verified is True
    assert first.closed_trades == 1
    assert first.reconciliation_checks == 1
    assert first.completed is True
    assert len(archive.load()) == 1

    restored = store.load()
    second = finalize_forward_paper_session(
        journal=restored,
        session_store=store,
        archive=archive,
        ended_ns=ended_ns + 600 * NANOSECOND,
    )

    assert second == first
    assert len(archive.load()) == 1
    assert archive.load()[0].session_event_hash == first.session_event_hash
