from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
from mastertrd.reconciliation import ExecutionState, Reconciler
from mastertrd.risk import RiskAction, RiskLimits, RiskSnapshot
from mastertrd.risk_runtime import OrderIntent, RiskRuntime
from mastertrd.risk_state import RiskStateProvider
from mastertrd.streaming import MarketStream


START_MS = 1_700_100_000_000
START_NS = START_MS * 1_000_000


def bar(event_id: str, offset_ms: int) -> dict[str, object]:
    return {
        "event_id": event_id,
        "venue": "BINANCE",
        "instrument": "BTCUSDT",
        "timeframe": "1m",
        "timestamp_ms": START_MS + offset_ms,
        "open": 50_000,
        "high": 50_100,
        "low": 49_900,
        "close": 50_050,
        "volume": 5,
    }


def tick(event_id: str, offset_ms: int) -> dict[str, object]:
    return {
        "event_id": event_id,
        "venue": "BINANCE",
        "instrument": "BTCUSDT",
        "timestamp_ms": START_MS + offset_ms,
        "bid": 50_000.0,
        "ask": 50_010.0,
        "bid_size": 2.0,
        "ask_size": 2.5,
        "last": 50_005.0,
        "last_size": 0.5,
        "realized_volatility": 0.03,
    }


def receipt() -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id="S-recovery",
        genome_hash="b" * 64,
        session_id="paper-recovery-1",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def limits() -> RiskLimits:
    return RiskLimits(
        max_order_notional=1e12,
        max_symbol_exposure=1e12,
        max_portfolio_exposure=1e12,
        max_daily_loss=1e12,
        max_drawdown=1.0,
        max_orders_per_minute=1_000_000,
    )


def state(*, btc: float = 0.0) -> ExecutionState:
    return ExecutionState(
        account_id="paper",
        positions={"BTCUSDT": btc},
        open_order_ids=frozenset(),
        balances={"USD": 100_000},
    )


def test_restart_restores_session_identity_and_replays_market_events_idempotently(tmp_path):
    path = tmp_path / "paper-session.json"
    store = JsonPaperSessionStore(path)
    original = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=START_NS)
    store.save(original)
    stable_state = state()

    first_dispatch: list[str] = []
    first_runtime = ExecutionRuntime(
        journal=original,
        session_store=store,
        risk_runtime=RiskRuntime(limits()),
        reconciler=Reconciler(),
        engine_state=lambda: stable_state,
        venue_state=lambda: stable_state,
        dispatch=lambda event: first_dispatch.append(event.event_id),
    )
    first_runtime.run(MarketStream([bar("market-e1", 0)]))
    assert first_dispatch == ["market-e1"]

    restored = store.load()
    assert restored.session_id == receipt().session_id
    assert restored.has_event("market-e1") is True

    second_dispatch: list[str] = []
    second_runtime = ExecutionRuntime(
        journal=restored,
        session_store=store,
        risk_runtime=RiskRuntime(limits()),
        reconciler=Reconciler(),
        engine_state=lambda: stable_state,
        venue_state=lambda: stable_state,
        dispatch=lambda event: second_dispatch.append(event.event_id),
    )
    report = second_runtime.run(
        MarketStream([bar("market-e1", 0), bar("market-e2", 60_000)])
    )

    assert second_dispatch == ["market-e2"]
    assert report.processed_events == 1
    assert report.duplicate_events == 1
    assert store.load().has_event("market-e2") is True


def test_reconciliation_mismatch_kills_system_before_first_market_event(tmp_path):
    store = JsonPaperSessionStore(tmp_path / "paper-session.json")
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=START_NS)
    store.save(journal)
    risk = RiskRuntime(limits())
    dispatched: list[str] = []

    runtime = ExecutionRuntime(
        journal=journal,
        session_store=store,
        risk_runtime=risk,
        reconciler=Reconciler(),
        engine_state=lambda: state(btc=1.0),
        venue_state=lambda: state(btc=0.0),
        dispatch=lambda event: dispatched.append(event.event_id),
    )
    report = runtime.run(
        MarketStream([bar("market-e1", 0), bar("market-e2", 60_000)])
    )

    assert report.system_killed is True
    assert report.reconciliation_errors == 1
    assert report.reconciliation_checks == 1
    assert report.processed_events == 0
    assert dispatched == []

    decision = risk.check_order(
        OrderIntent(
            strategy_id="S-recovery",
            symbol="BTCUSDT.BINANCE",
            venue="BINANCE",
            side="BUY",
            quantity=0.01,
            order_type="MARKET",
        ),
        RiskSnapshot(
            order_notional=500.0,
            symbol_exposure=0.0,
            portfolio_exposure=0.0,
            daily_pnl=0.0,
            drawdown=0.0,
            orders_last_minute=0,
        ),
    )
    assert decision.action is RiskAction.KILL_SYSTEM
    assert "reconciliation" in decision.reason.lower()


def test_execution_runtime_refreshes_owned_market_reconciliation_and_api_state(tmp_path):
    now_seconds = (START_MS + 1_000) / 1_000.0
    provider = RiskStateProvider(clock=lambda: now_seconds, max_market_age_seconds=5.0)
    provider.update_account_state(
        symbol="BTCUSDT.BINANCE",
        portfolio_id="default",
        symbol_exposure=1_000.0,
        portfolio_exposure=2_000.0,
        daily_pnl=25.0,
        drawdown=0.01,
        leverage=1.2,
        correlated_exposure=500.0,
    )
    risk = RiskRuntime(limits(), state_provider=provider)
    risk.update_api_health(
        venue="BINANCE",
        healthy=True,
        error_rate=0.01,
        latency_ms=25.0,
    )

    store = JsonPaperSessionStore(tmp_path / "paper-session.json")
    journal = PaperSessionJournal(receipt(), code_hash="code-v1", started_ns=START_NS)
    store.save(journal)
    stable_state = state()
    runtime = ExecutionRuntime(
        journal=journal,
        session_store=store,
        risk_runtime=risk,
        reconciler=Reconciler(),
        engine_state=lambda: stable_state,
        venue_state=lambda: stable_state,
        dispatch=lambda event: None,
    )

    runtime.run(MarketStream([tick("market-t1", 0)]))
    snapshot = risk.snapshot_for_order(
        OrderIntent(
            strategy_id="S-recovery",
            symbol="BTCUSDT.BINANCE",
            venue="BINANCE",
            side="BUY",
            quantity=0.01,
            order_type="MARKET",
        ),
        reference_price=50_005.0,
    )

    expected_spread_bps = (10.0 / 50_005.0) * 10_000.0
    assert snapshot.data_stale is False
    assert snapshot.spread_bps == expected_spread_bps
    assert snapshot.realized_volatility == 0.03
    assert snapshot.reconciliation_ok is True
    assert snapshot.reconciliation_age_seconds == 1.0
    assert snapshot.venue_healthy is True
    assert snapshot.api_error_rate == 0.01
    assert snapshot.api_latency_ms == 25.0
