import json
from decimal import Decimal

from mastertrd.contracts import RuntimeMode
from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.genome import StrategyGenome
from mastertrd.paper_archive import JsonPaperReportArchive
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
from mastertrd.reconciliation import ExecutionState, Reconciler
from mastertrd.risk import RiskLimits
from mastertrd.risk_runtime import RiskRuntime
from mastertrd.runtime import RuntimeConfig
from mastertrd.runtime_factory import build_execution_runtime
from mastertrd.streaming import MarketStream


START_MS = 1_700_500_000_000
START_NS = START_MS * 1_000_000


def _candidate_payload() -> dict[str, object]:
    return StrategyGenome(
        strategy_id="paper-production-trend",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8, "trade_size": "0.01000"},
        exit={"kind": "cross_reverse"},
        allow_short=False,
    ).canonical_payload()


def _feed_event(event_id: str = "paper-production-1", *, offset_ms: int = 0) -> dict[str, object]:
    return {
        "event_id": event_id,
        "venue": "BINANCE",
        "instrument": "BTCUSDT",
        "timeframe": "1m",
        "timestamp_ms": START_MS + offset_ms,
        "open": 60_000.0,
        "high": 60_100.0,
        "low": 59_900.0,
        "close": 60_050.0,
        "volume": 1.0,
        "spread_bps": 5.0,
        "realized_volatility": 0.02,
    }


def _paper_environment(tmp_path, *, feed_path) -> dict[str, str]:
    return {
        "MASTERTRD_CANDIDATE_MANIFEST": str(tmp_path / "candidate.json"),
        "MASTERTRD_SESSION_STATE": str(tmp_path / "current-session.json"),
        "MASTERTRD_PAPER_ARCHIVE": str(tmp_path / "paper-reports.json"),
        "MASTERTRD_PAPER_HISTORY_DIR": str(tmp_path / "paper-sessions"),
        "MASTERTRD_PAPER_ROTATION_REQUEST": str(tmp_path / "paper-rotate.request"),
        "MASTERTRD_CODE_HASH": "code-production-v1",
        "MASTERTRD_PAPER_START_NS": str(START_NS),
        "MASTERTRD_SESSION_NONCE": "production-paper",
        "MASTERTRD_PUBLIC_FEED_FIXTURE": str(feed_path),
    }


def _runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        mode=RuntimeMode.PAPER,
        live_trading_enabled=False,
        oracle_enabled=False,
    )


def test_controlled_paper_completion_archives_verified_report_and_preserves_final_session(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    feed_path = tmp_path / "feed.jsonl"
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")
    feed_path.write_text(json.dumps(_feed_event()) + "\n", encoding="utf-8")
    environ = _paper_environment(tmp_path, feed_path=feed_path)

    runtime = build_execution_runtime(_runtime_config(), environ)
    run_report = runtime.run()
    assert run_report.system_killed is False

    session_id = runtime._journal.session_id
    runtime.complete_session()
    runtime.close()

    archive = JsonPaperReportArchive(environ["MASTERTRD_PAPER_ARCHIVE"])
    reports = archive.load()
    assert len(reports) == 1
    assert reports[0].session_id == session_id
    assert reports[0].strategy_id == "paper-production-trend"
    assert reports[0].code_hash == "code-production-v1"
    assert reports[0].provenance_verified is True
    assert reports[0].completed is True

    assert not (tmp_path / "current-session.json").exists()
    history_path = tmp_path / "paper-sessions" / f"{session_id}.json"
    assert history_path.exists()
    restored = JsonPaperSessionStore(history_path).load()
    assert restored.finalized_report == reports[0]


def test_paper_factory_recovers_finalized_current_session_before_starting_a_new_one(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    feed_path = tmp_path / "feed.jsonl"
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")
    feed_path.write_text(json.dumps(_feed_event()) + "\n", encoding="utf-8")
    environ = _paper_environment(tmp_path, feed_path=feed_path)

    initial = build_execution_runtime(_runtime_config(), environ)
    initial.run()
    old_session_id = initial._journal.session_id
    ended_ns = max(initial._journal.latest_timestamp_ns, START_NS + 60_000_000_000)
    stranded_report = initial._journal.finalize(ended_ns=ended_ns)
    initial._session_store.save(initial._journal)
    initial.close()

    recovered = build_execution_runtime(_runtime_config(), environ)

    assert recovered._journal.session_id != old_session_id
    assert recovered._journal.finalized_report is None
    archive = JsonPaperReportArchive(environ["MASTERTRD_PAPER_ARCHIVE"])
    assert archive.load() == (stranded_report,)
    history_path = tmp_path / "paper-sessions" / f"{old_session_id}.json"
    assert JsonPaperSessionStore(history_path).load().finalized_report == stranded_report


def test_rotation_request_waits_for_authoritative_flat_execution_state(tmp_path):
    receipt = PaperStartReceipt(
        strategy_id="paper-flat-boundary",
        genome_hash="a" * 64,
        session_id="paper-flat-session",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )
    journal = PaperSessionJournal(receipt, code_hash="code-flat", started_ns=START_NS)
    store = JsonPaperSessionStore(tmp_path / "flat-session.json")
    state = {
        "value": ExecutionState(
            account_id="paper:paper-flat-session",
            positions={"BTCUSDT.BINANCE": Decimal("0.01")},
            open_order_ids=frozenset(),
            balances={"USDT": Decimal("100000")},
        )
    }

    def dispatch(_event):
        state["value"] = ExecutionState(
            account_id="paper:paper-flat-session",
            positions={},
            open_order_ids=frozenset(),
            balances={"USDT": Decimal("100000")},
        )

    runtime = ExecutionRuntime(
        journal=journal,
        session_store=store,
        risk_runtime=RiskRuntime(
            RiskLimits(
                max_order_notional=1_000.0,
                max_symbol_exposure=5_000.0,
                max_portfolio_exposure=10_000.0,
                max_daily_loss=500.0,
                max_drawdown=0.10,
                max_orders_per_minute=30,
            )
        ),
        reconciler=Reconciler(),
        engine_state=lambda: state["value"],
        venue_state=lambda: state["value"],
        dispatch=dispatch,
        stream=MarketStream(
            [
                _feed_event("flat-boundary-1"),
                _feed_event("flat-boundary-2", offset_ms=60_000),
            ]
        ),
        rotation_requested=lambda: True,
    )

    report = runtime.run()

    assert report.processed_events == 1
    assert report.session_rotation_requested is True
    assert state["value"].positions == {}
