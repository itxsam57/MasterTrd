from mastertrd.champion import ChampionComparisonPolicy
from mastertrd.contracts import StrategyState
from mastertrd.forward_scheduler import ForwardPromotionScheduler
from mastertrd.genome import StrategyGenome
from mastertrd.paper_archive import JsonPaperReportArchive
from mastertrd.paper_cycle import finalize_forward_paper_session, start_generated_paper_cycle
from mastertrd.paper_forward import PaperMinimumPolicy
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal


NS = 1_000_000_000


def _candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-forward-lifecycle",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={
            "kind": "ema_cross",
            "fast_period": 5,
            "slow_period": 20,
            "trade_size": "0.10",
        },
        exit={"kind": "cross_reverse"},
    )


def _scheduler() -> ForwardPromotionScheduler:
    return ForwardPromotionScheduler(
        paper_policy=PaperMinimumPolicy(
            min_sessions=2,
            min_duration_seconds=7_200,
            min_closed_trades=4,
            min_total_return=0.0,
            max_drawdown=0.20,
        ),
        champion_policy=ChampionComparisonPolicy(
            min_closed_trades=4,
            min_score_improvement=0.01,
            max_drawdown_ratio=1.25,
        ),
    )


def _archive_session(*, candidate, archive, root, nonce: str, started_ns: int) -> None:
    paper_start = start_generated_paper_cycle(candidate=candidate, session_nonce=nonce)
    assert paper_start.promotion.allowed is True
    assert paper_start.promotion.target is StrategyState.PAPER
    assert paper_start.evidence.evidence_type == "paper_started"

    store = JsonPaperSessionStore(root / f"{nonce}.json")
    journal = PaperSessionJournal(
        paper_start.receipt,
        code_hash="forward-code-v1",
        started_ns=started_ns,
    )
    journal.record_closed_trade(
        f"{nonce}-trade-1",
        0.02,
        timestamp_ns=started_ns + 60 * NS,
    )
    journal.record_closed_trade(
        f"{nonce}-trade-2",
        0.01,
        timestamp_ns=started_ns + 120 * NS,
    )
    journal.record_reconciliation(
        f"{nonce}-reconcile",
        ok=True,
        timestamp_ns=started_ns + 180 * NS,
    )
    store.save(journal)
    finalize_forward_paper_session(
        journal=journal,
        session_store=store,
        archive=archive,
        ended_ns=started_ns + 3_600 * NS,
    )


def test_scheduler_runs_hidden_pass_through_real_paper_reports_to_champion(tmp_path):
    candidate = _candidate()
    archive = JsonPaperReportArchive(tmp_path / "paper-reports.json")
    _archive_session(
        candidate=candidate,
        archive=archive,
        root=tmp_path,
        nonce="forward-1",
        started_ns=10_000 * NS,
    )
    _archive_session(
        candidate=candidate,
        archive=archive,
        root=tmp_path,
        nonce="forward-2",
        started_ns=20_000 * NS,
    )

    cycle = _scheduler().evaluate(
        candidate=candidate,
        archive=archive,
        incumbent_paper=None,
    )

    assert cycle.paper_evidence.evidence_type == "paper_minimum_evidence"
    assert cycle.paper_evidence.passed is True
    assert cycle.challenger_promotion.allowed is True
    assert cycle.challenger_promotion.target is StrategyState.CHALLENGER
    assert cycle.champion_evidence is not None
    assert cycle.champion_evidence.evidence_type == "champion_comparison"
    assert cycle.champion_evidence.passed is True
    assert cycle.champion_promotion is not None
    assert cycle.champion_promotion.allowed is True
    assert cycle.champion_promotion.target is StrategyState.CHAMPION


def test_scheduler_never_skips_challenger_when_forward_minimum_is_missing(tmp_path):
    candidate = _candidate()
    archive = JsonPaperReportArchive(tmp_path / "paper-reports.json")
    _archive_session(
        candidate=candidate,
        archive=archive,
        root=tmp_path,
        nonce="only-session",
        started_ns=30_000 * NS,
    )

    cycle = _scheduler().evaluate(
        candidate=candidate,
        archive=archive,
        incumbent_paper=None,
    )

    assert cycle.paper_evidence.passed is False
    assert cycle.challenger_promotion.allowed is False
    assert cycle.challenger_promotion.target is StrategyState.CHALLENGER
    assert cycle.champion_evidence is None
    assert cycle.champion_promotion is None
