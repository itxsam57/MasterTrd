from mastertrd.contracts import RuntimeMode
from mastertrd.genome import StrategyGenome
from mastertrd.live_evidence import LiveEvidenceStatus, run_reconciliation_probe
from mastertrd.reconciliation import ExecutionState


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="RECON-EVIDENCE-1",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross"},
        exit={"kind": "cross_reverse"},
    )


def state(*, position: str = "0.1", orders: frozenset[str] = frozenset({"order-1"})) -> ExecutionState:
    return ExecutionState(
        account_id="testnet-account",
        positions={"BTCUSDT.BINANCE": position},
        open_order_ids=orders,
        balances={"USDT": "1000"},
    )


def test_reconciliation_probe_exercises_real_reconciler_and_passes_matching_state():
    evidence = run_reconciliation_probe(
        candidate(),
        engine_state=state(),
        venue_state=state(),
        fills_match=True,
        no_unexpected_orders=True,
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.TESTNET,
    )

    assert evidence.evidence_type == "reconciliation_test"
    assert evidence.status is LiveEvidenceStatus.COMPLETED
    assert evidence.passed is True
    assert evidence.metrics["state_reconciliation_ok"] == 1.0
    assert evidence.metrics["fills_match"] == 1.0
    assert evidence.metrics["no_unexpected_orders"] == 1.0


def test_reconciliation_probe_fails_on_position_mismatch():
    evidence = run_reconciliation_probe(
        candidate(),
        engine_state=state(position="0.1"),
        venue_state=state(position="0.2"),
        fills_match=True,
        no_unexpected_orders=True,
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.TESTNET,
    )

    assert evidence.status is LiveEvidenceStatus.FAILED
    assert evidence.passed is False
    assert evidence.metrics["state_reconciliation_ok"] == 0.0


def test_reconciliation_probe_wrong_runtime_mode_fails_closed():
    evidence = run_reconciliation_probe(
        candidate(),
        engine_state=state(),
        venue_state=state(),
        fills_match=True,
        no_unexpected_orders=True,
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.PAPER,
    )

    assert evidence.status is LiveEvidenceStatus.WRONG_RUNTIME_MODE
    assert evidence.passed is False
