from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.paper_archive import JsonPaperReportArchive
from mastertrd.paper_challenger import evaluate_archived_challenger
from mastertrd.paper_forward import PaperForwardReport, PaperMinimumPolicy


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-challenger",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def report(genome: StrategyGenome, session_id: str, total_return: float) -> PaperForwardReport:
    return PaperForwardReport(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        session_id=session_id,
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        duration_seconds=3600,
        closed_trades=6,
        total_return=total_return,
        max_drawdown=0.05,
        reconciliation_errors=0,
        completed=True,
        code_hash="code-v1",
        reconciliation_checks=1,
        session_event_hash=(session_id.encode().hex().ljust(64, "0")[:64]),
        provenance_verified=True,
    )


def policy() -> PaperMinimumPolicy:
    return PaperMinimumPolicy(
        min_sessions=2,
        min_duration_seconds=7200,
        min_closed_trades=10,
        min_total_return=0.0,
        max_drawdown=0.20,
    )


def test_challenger_decision_reads_verified_reports_only_from_archive(tmp_path):
    genome = candidate()
    archive = JsonPaperReportArchive(tmp_path / "reports.json")
    archive.append(report(genome, "session-1", 0.02))
    archive.append(report(genome, "session-2", 0.01))

    cycle = evaluate_archived_challenger(
        candidate=genome,
        archive=archive,
        policy=policy(),
    )

    assert cycle.evidence.passed is True
    assert cycle.evidence.code_hash == "code-v1"
    assert cycle.promotion.allowed is True
    assert cycle.promotion.target is StrategyState.CHALLENGER
    assert cycle.report_count == 2


def test_archive_with_insufficient_forward_evidence_cannot_promote(tmp_path):
    genome = candidate()
    archive = JsonPaperReportArchive(tmp_path / "reports.json")
    archive.append(report(genome, "session-1", 0.02))

    cycle = evaluate_archived_challenger(
        candidate=genome,
        archive=archive,
        policy=policy(),
    )

    assert cycle.evidence.passed is False
    assert cycle.promotion.allowed is False
    assert "paper_minimum_evidence" in cycle.promotion.missing_evidence
