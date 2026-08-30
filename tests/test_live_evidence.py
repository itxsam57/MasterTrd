import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.genome import StrategyGenome
from mastertrd.live_evidence import LiveEvidenceStatus, run_risk_review, run_testnet_smoke
from mastertrd.risk import RiskLimits


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="LIVE-EVIDENCE-1",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20},
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


def test_risk_review_is_bound_to_testnet_code_and_dataset_identity():
    evidence = run_risk_review(
        candidate(),
        limits=limits(),
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.TESTNET,
    )

    assert evidence.evidence_type == "risk_review"
    assert evidence.dataset_hash == "dataset-001"
    assert evidence.code_hash == "code-001"
    assert evidence.status is LiveEvidenceStatus.COMPLETED
    assert evidence.passed is True


def test_live_probe_evidence_fails_when_runtime_mode_is_not_testnet():
    evidence = run_risk_review(
        candidate(),
        limits=limits(),
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.PAPER,
    )

    assert evidence.status is LiveEvidenceStatus.WRONG_RUNTIME_MODE
    assert evidence.passed is False


def test_testnet_smoke_reports_credentials_unavailable_without_submitting():
    submissions: list[float] = []
    evidence = run_testnet_smoke(
        candidate(),
        environ={},
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.TESTNET,
        venue_minimum_notional=5.0,
        submit_test_order=lambda notional: submissions.append(notional) or True,
    )

    assert evidence.evidence_type == "testnet_smoke"
    assert evidence.status is LiveEvidenceStatus.CREDENTIALS_UNAVAILABLE
    assert evidence.passed is False
    assert evidence.metrics["credentials_available"] == 0.0
    assert submissions == []


def test_testnet_smoke_uses_only_venue_minimum_notional_and_never_live_namespace():
    submissions: list[float] = []
    evidence = run_testnet_smoke(
        candidate(),
        environ={
            "BINANCE_TESTNET_API_KEY": "test-key",
            "BINANCE_TESTNET_API_SECRET": "test-secret",
            "BINANCE_TESTNET_ACCOUNT_ID": "test-account",
            "BINANCE_LIVE_API_KEY": "must-not-be-used",
            "BINANCE_LIVE_API_SECRET": "must-not-be-used",
            "BINANCE_LIVE_ACCOUNT_ID": "must-not-be-used",
        },
        dataset_hash="dataset-001",
        code_hash="code-001",
        runtime_mode=RuntimeMode.TESTNET,
        venue_minimum_notional=5.0,
        submit_test_order=lambda notional: submissions.append(notional) or True,
    )

    assert evidence.status is LiveEvidenceStatus.COMPLETED
    assert evidence.passed is True
    assert submissions == [5.0]
    assert evidence.metrics["submitted_notional"] == 5.0


def test_live_evidence_rejects_empty_identity_hashes():
    with pytest.raises(ValueError, match="dataset_hash"):
        run_risk_review(
            candidate(),
            limits=limits(),
            dataset_hash="",
            code_hash="code-001",
            runtime_mode=RuntimeMode.TESTNET,
        )
