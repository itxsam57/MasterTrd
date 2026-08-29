import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.live_readiness import (
    ReconciliationTestReceipt,
    KillSwitchTestReceipt,
    kill_switch_test_evidence,
    reconciliation_test_evidence,
    risk_review_evidence,
)
from mastertrd.risk import RiskAction, RiskLimits, RiskSnapshot, evaluate_risk


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-live-candidate",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
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


def test_manual_emergency_stop_is_a_system_kill_input():
    snapshot = RiskSnapshot(
        order_notional=10.0,
        symbol_exposure=20.0,
        portfolio_exposure=100.0,
        daily_pnl=0.0,
        drawdown=0.01,
        orders_last_minute=0,
        emergency_stop=True,
    )
    assert evaluate_risk(limits(), snapshot) is RiskAction.KILL_SYSTEM


def test_risk_review_proves_fail_closed_risk_semantics():
    candidate = genome()
    evidence = risk_review_evidence(candidate, limits())
    assert evidence.evidence_type == "risk_review"
    assert evidence.passed is True
    assert evidence.metrics["normal_order_allowed"] == 1.0
    assert evidence.metrics["stale_data_system_kill"] == 1.0
    assert evidence.metrics["reconciliation_system_kill"] == 1.0
    assert evidence.metrics["daily_loss_strategy_kill"] == 1.0
    assert evidence.metrics["drawdown_strategy_kill"] == 1.0
    assert evidence.metrics["rate_limit_blocks"] == 1.0
    assert evidence.metrics["notional_limit_blocks"] == 1.0
    assert evidence.metrics["symbol_exposure_blocks"] == 1.0
    assert evidence.metrics["portfolio_exposure_blocks"] == 1.0
    assert evidence.metrics["manual_emergency_stop_system_kill"] == 1.0


def test_risk_review_rejects_unsafe_live_limits():
    candidate = genome()
    with pytest.raises(ValueError, match="positive"):
        risk_review_evidence(
            candidate,
            RiskLimits(0.0, 200.0, 500.0, 50.0, 0.20, 10),
        )
    with pytest.raises(ValueError, match="hierarchy"):
        risk_review_evidence(
            candidate,
            RiskLimits(300.0, 200.0, 500.0, 50.0, 0.20, 10),
        )
    with pytest.raises(ValueError, match="max_drawdown"):
        risk_review_evidence(
            candidate,
            RiskLimits(100.0, 200.0, 500.0, 50.0, 1.20, 10),
        )


def test_reconciliation_receipt_requires_every_account_surface_to_match():
    candidate = genome()
    good = ReconciliationTestReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        account_snapshot_id="snapshot-001",
        balances_match=True,
        positions_match=True,
        open_orders_match=True,
        fills_match=True,
        no_unexpected_orders=True,
        completed=True,
    )
    evidence = reconciliation_test_evidence(candidate, good)
    assert evidence.evidence_type == "reconciliation_test"
    assert evidence.passed is True

    bad = ReconciliationTestReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        account_snapshot_id="snapshot-002",
        balances_match=True,
        positions_match=False,
        open_orders_match=True,
        fills_match=True,
        no_unexpected_orders=True,
        completed=True,
    )
    assert reconciliation_test_evidence(candidate, bad).passed is False


def test_reconciliation_receipt_is_bound_to_candidate_identity():
    candidate = genome()
    wrong = ReconciliationTestReceipt(
        strategy_id="other",
        genome_hash=candidate.genome_hash,
        account_snapshot_id="snapshot-wrong",
        balances_match=True,
        positions_match=True,
        open_orders_match=True,
        fills_match=True,
        no_unexpected_orders=True,
        completed=True,
    )
    with pytest.raises(ValueError, match="strategy_id"):
        reconciliation_test_evidence(candidate, wrong)


def test_kill_switch_receipt_requires_manual_and_automatic_kills():
    candidate = genome()
    good = KillSwitchTestReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        test_id="kill-test-001",
        manual_stop_verified=True,
        stale_data_kill_verified=True,
        reconciliation_failure_kill_verified=True,
        daily_loss_kill_verified=True,
        drawdown_kill_verified=True,
        completed=True,
    )
    evidence = kill_switch_test_evidence(candidate, good)
    assert evidence.evidence_type == "kill_switch_test"
    assert evidence.passed is True

    incomplete = KillSwitchTestReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        test_id="kill-test-002",
        manual_stop_verified=False,
        stale_data_kill_verified=True,
        reconciliation_failure_kill_verified=True,
        daily_loss_kill_verified=True,
        drawdown_kill_verified=True,
        completed=True,
    )
    assert kill_switch_test_evidence(candidate, incomplete).passed is False


def test_all_three_safety_receipts_are_required_for_live_eligibility():
    candidate = genome()
    risk = risk_review_evidence(candidate, limits())
    reconciliation = reconciliation_test_evidence(
        candidate,
        ReconciliationTestReceipt(
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            account_snapshot_id="snapshot-live",
            balances_match=True,
            positions_match=True,
            open_orders_match=True,
            fills_match=True,
            no_unexpected_orders=True,
            completed=True,
        ),
    )
    kill = kill_switch_test_evidence(
        candidate,
        KillSwitchTestReceipt(
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            test_id="kill-live",
            manual_stop_verified=True,
            stale_data_kill_verified=True,
            reconciliation_failure_kill_verified=True,
            daily_loss_kill_verified=True,
            drawdown_kill_verified=True,
            completed=True,
        ),
    )

    missing = evaluate_validated_promotion(
        StrategyState.CHAMPION,
        StrategyState.LIVE_ELIGIBLE,
        candidate,
        [risk, reconciliation],
    )
    assert missing.allowed is False

    complete = evaluate_validated_promotion(
        StrategyState.CHAMPION,
        StrategyState.LIVE_ELIGIBLE,
        candidate,
        [risk, reconciliation, kill],
    )
    assert complete.allowed is True
