import json
from dataclasses import replace

import pytest

from mastertrd.paper_archive import JsonPaperReportArchive
from mastertrd.paper_forward import PaperForwardReport


def report(session_id: str, *, code_hash: str = "code-v1") -> PaperForwardReport:
    return PaperForwardReport(
        strategy_id="S-archive",
        genome_hash="g" * 64,
        session_id=session_id,
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        duration_seconds=3600,
        closed_trades=5,
        total_return=0.01,
        max_drawdown=0.03,
        reconciliation_errors=0,
        completed=True,
        code_hash=code_hash,
        reconciliation_checks=1,
        session_event_hash=(session_id.encode().hex().ljust(64, "0")[:64]),
        provenance_verified=True,
    )


def test_archive_persists_verified_reports_and_replays_identical_session_idempotently(tmp_path):
    path = tmp_path / "paper-reports.json"
    archive = JsonPaperReportArchive(path)
    first = report("session-1")
    second = report("session-2")

    archive.append(first)
    archive.append(second)

    restored = JsonPaperReportArchive(path).load()
    assert [item.session_id for item in restored] == ["session-1", "session-2"]
    assert all(item.provenance_verified for item in restored)

    archive.append(first)
    assert archive.load() == restored

    with pytest.raises(ValueError, match="conflicting"):
        archive.append(replace(first, total_return=0.99))


def test_archive_rejects_unverified_reports_and_mixed_strategy_or_code_identity(tmp_path):
    archive = JsonPaperReportArchive(tmp_path / "paper-reports.json")
    first = report("session-1")
    archive.append(first)

    with pytest.raises(ValueError, match="verified"):
        archive.append(PaperForwardReport(
            strategy_id=first.strategy_id,
            genome_hash=first.genome_hash,
            session_id="session-unverified",
            venue="SANDBOX",
            engine="nautilus_trader",
            engine_version="1.231.0",
            duration_seconds=1,
            closed_trades=0,
            total_return=0.0,
            max_drawdown=0.0,
            reconciliation_errors=0,
            completed=False,
        ))
    with pytest.raises(ValueError, match="code_hash"):
        archive.append(report("session-2", code_hash="code-v2"))


def test_archive_tampering_fails_closed(tmp_path):
    path = tmp_path / "paper-reports.json"
    archive = JsonPaperReportArchive(path)
    archive.append(report("session-1"))

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["reports"][0]["total_return"] = 9.99
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity"):
        JsonPaperReportArchive(path).load()
