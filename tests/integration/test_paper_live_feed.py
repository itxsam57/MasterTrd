from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
from mastertrd.reconciliation import ExecutionState, Reconciler
from mastertrd.risk import RiskLimits
from mastertrd.risk_runtime import RiskRuntime
from mastertrd.streaming import MarketStream


START_MS = 1_700_000_000_000
START_NS = START_MS * 1_000_000


def bar(event_id: str, offset_ms: int) -> dict[str, object]:
    return {
        "event_id": event_id,
        "venue": "BINANCE",
        "instrument": "ETHUSDT",
        "timeframe": "1m",
        "timestamp_ms": START_MS + offset_ms,
        "open": 2000,
        "high": 2010,
        "low": 1995,
        "close": 2005,
        "volume": 10,
    }


def receipt() -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id="S-live-feed",
        genome_hash="a" * 64,
        session_id="paper-live-feed-1",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def risk_runtime() -> RiskRuntime:
    return RiskRuntime(
        RiskLimits(
            max_order_notional=1e12,
            max_symbol_exposure=1e12,
            max_portfolio_exposure=1e12,
            max_daily_loss=1e12,
            max_drawdown=1.0,
            max_orders_per_minute=1_000_000,
        )
    )


def account_state() -> ExecutionState:
    return ExecutionState(
        account_id="paper",
        positions={},
        open_order_ids=frozenset(),
        balances={"USD": 100_000},
    )


def test_disconnect_reconnect_replay_does_not_duplicate_order_dispatch(tmp_path):
    store = JsonPaperSessionStore(tmp_path / "paper-session.json")
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=START_NS)
    store.save(journal)
    dispatched: list[str] = []
    state = account_state()

    runtime = ExecutionRuntime(
        journal=journal,
        session_store=store,
        risk_runtime=risk_runtime(),
        reconciler=Reconciler(),
        engine_state=lambda: state,
        venue_state=lambda: state,
        dispatch=lambda event: dispatched.append(event.event_id),
    )

    first = MarketStream([bar("market-e1", 0)])
    first_report = runtime.run(first)
    reconnect = first.reconnect([bar("market-e1", 0), bar("market-e2", 60_000)])
    second_report = runtime.run(reconnect)

    assert dispatched == ["market-e1", "market-e2"]
    assert first_report.processed_events == 1
    assert first_report.duplicate_events == 0
    assert second_report.processed_events == 1
    assert second_report.duplicate_events == 1
    assert second_report.reconciliation_checks == 1

    restored = store.load()
    assert restored.has_event("market-e1") is True
    assert restored.has_event("market-e2") is True
