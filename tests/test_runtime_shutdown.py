import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.live_node import NodeReadiness, run_node
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
from mastertrd.reconciliation import ExecutionState, Reconciler
from mastertrd.risk import RiskLimits
from mastertrd.risk_runtime import RiskRuntime
from mastertrd.runtime import RuntimeConfig


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


def test_run_node_closes_execution_runtime_when_run_raises():
    calls: list[str] = []

    class CrashingExecutionRuntime:
        def run(self, *, stop_requested):
            calls.append("run")
            assert stop_requested() is False
            raise RuntimeError("execution failed")

        def close(self):
            calls.append("close")

    runtime = RuntimeConfig(
        mode=RuntimeMode.PAPER,
        live_trading_enabled=False,
        oracle_enabled=False,
    )

    with pytest.raises(RuntimeError, match="execution failed"):
        run_node(
            runtime,
            {},
            stop_requested=lambda: False,
            sleep=lambda _seconds: pytest.fail("runtime-backed node must not sleep"),
            heartbeat=lambda state: calls.append(state.value),
            interval_seconds=5.0,
            execution_runtime=CrashingExecutionRuntime(),
        )

    assert calls == [NodeReadiness.PAPER_READY.value, "run", "close"]
