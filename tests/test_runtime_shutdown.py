
from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
from mastertrd.reconciliation import ExecutionState, Reconciler
from mastertrd.risk import RiskLimits
from mastertrd.risk_runtime import RiskRuntime


START_NS = 1_700_400_000_000_000_000


def _runtime_with_finalizer(tmp_path, finalized: list[str]) -> ExecutionRuntime:
    receipt = PaperStartReceipt(
        strategy_id="shutdown-test",
        genome_hash="c" * 64,
        session_id="paper-shutdown-1",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )
    journal = PaperSessionJournal(receipt, code_hash="code-v2", started_ns=START_NS)
    store = JsonPaperSessionStore(tmp_path / "paper-session.json")
    store.save(journal)
    state = ExecutionState(
        account_id="paper-shutdown-1",
        positions={},
        open_order_ids=frozenset(),
        balances={},
    )
    return ExecutionRuntime(
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
        engine_state=lambda: state,
        venue_state=lambda: state,
        dispatch=lambda _event: None,
        finalizer=lambda: finalized.append("closed"),
    )


def test_execution_runtime_close_finalizes_once_without_breaking_reusable_run(tmp_path):
    finalized: list[str] = []
    runtime = _runtime_with_finalizer(tmp_path, finalized)

    runtime.close()
    runtime.close()

    assert finalized == ["closed"]


