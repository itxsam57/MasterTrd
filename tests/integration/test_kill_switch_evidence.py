from mastertrd.contracts import RuntimeMode
from mastertrd.genome import StrategyGenome
from mastertrd.live_evidence import LiveEvidenceStatus, run_kill_switch_probe
from mastertrd.risk import RiskAction, RiskLimits, RiskSnapshot
from mastertrd.risk_runtime import OrderIntent, RiskRuntime


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="KILL-EVIDENCE-1",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross"},
        exit={"kind": "cross_reverse"},
    )


def limits() -> RiskLimits:
    return RiskLimits(
        max_order_notional=100.0,
        max_symbol_exposure=200.0,
        max_portfolio_exposure=500.0,
        max_daily_loss=50.0,
        max_drawdown=0.20,
        max_orders_per_minute=10,
    )


def intent() -> OrderIntent:
    return OrderIntent(
        strategy_id=candidate().strategy_id,
        symbol="BTCUSDT.BINANCE",
        venue="BINANCE",
        side="BUY",
        quantity=0.001,
        order_type="MARKET",
    )


def snapshot() -> RiskSnapshot:
    return RiskSnapshot(
        order_notional=10.0,
        symbol_exposure=0.0,
        portfolio_exposure=0.0,
        daily_pnl=0.0,
        drawdown=0.0,
        orders_last_minute=0,
    )


def test_kill_switch_probe_proves_post_kill_submission_is_blocked():
    runtime = RiskRuntime(limits())
    submissions: list[str] = []

    evidence = run_kill_switch_probe(
        candidate(),
        risk_runtime=runtime,
        intent=intent(),
        snapshot=snapshot(),
        submit_order=lambda order: submissions.append(order.fingerprint),
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.TESTNET,
    )

    assert evidence.evidence_type == "kill_switch_test"
    assert evidence.status is LiveEvidenceStatus.COMPLETED
    assert evidence.passed is True
    assert evidence.metrics["pre_kill_allowed"] == 1.0
    assert evidence.metrics["post_kill_system_kill"] == 1.0
    assert evidence.metrics["post_kill_submission_blocked"] == 1.0
    assert submissions == [intent().fingerprint]
    assert runtime.decisions[-1].action is RiskAction.KILL_SYSTEM


def test_kill_switch_probe_in_wrong_runtime_mode_cannot_submit_or_pass():
    runtime = RiskRuntime(limits())
    submissions: list[str] = []

    evidence = run_kill_switch_probe(
        candidate(),
        risk_runtime=runtime,
        intent=intent(),
        snapshot=snapshot(),
        submit_order=lambda order: submissions.append(order.fingerprint),
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.PAPER,
    )

    assert evidence.status is LiveEvidenceStatus.WRONG_RUNTIME_MODE
    assert evidence.passed is False
    assert submissions == []
