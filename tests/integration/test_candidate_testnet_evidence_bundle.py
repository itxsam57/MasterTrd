from __future__ import annotations

from decimal import Decimal

from mastertrd.contracts import RuntimeMode
from mastertrd.genome import StrategyGenome
from mastertrd.live_evidence import LiveEvidenceStatus, LiveValidationEvidence
from mastertrd.testnet_candidate import (
    TestnetCandidateManifest,
    build_candidate_testnet_evidence_bundle,
    candidate_testnet_bundle_identity_ok,
)
from mastertrd.venue import BinanceProduct


def _candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-CHAMPION-BUNDLE-001",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20},
        exit={"kind": "cross_reverse"},
        risk={"risk_fraction": 0.01},
    )


def _manifest() -> TestnetCandidateManifest:
    candidate = _candidate()
    return TestnetCandidateManifest.from_candidate(
        candidate,
        code_hash="code-bundle-001",
        dataset_hash="dataset-bundle-001",
        product=BinanceProduct.SPOT,
        probe_instrument="BTCUSDT.BINANCE",
        order_notional_cap=Decimal("10"),
    )


def _smoke(*, passed: bool, status: LiveEvidenceStatus) -> LiveValidationEvidence:
    candidate = _candidate()
    return LiveValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="testnet_smoke",
        dataset_hash="dataset-bundle-001",
        code_hash="code-bundle-001",
        engine="mastertrd_live_probe",
        engine_version="1",
        passed=passed,
        metrics={
            "credentials_available": float(passed),
            "testnet_mode": 1.0,
            "order_submitted": float(passed),
            "submitted_notional": 5.0 if passed else 0.0,
        },
        status=status,
    )


def test_candidate_testnet_evidence_bundle_runs_three_safety_probes_and_uses_real_smoke_identity():
    manifest = _manifest()
    bundle = build_candidate_testnet_evidence_bundle(
        manifest,
        smoke_evidence=_smoke(passed=True, status=LiveEvidenceStatus.COMPLETED),
        runtime_mode=RuntimeMode.TESTNET,
    )

    assert {record.evidence_type for record in bundle.records} == {
        "risk_review",
        "reconciliation_test",
        "kill_switch_test",
        "testnet_smoke",
    }
    assert all(record.strategy_id == manifest.strategy_id for record in bundle.records)
    assert all(record.genome_hash == manifest.genome_hash for record in bundle.records)
    assert all(record.code_hash == manifest.code_hash for record in bundle.records)
    assert all(record.dataset_hash == manifest.dataset_hash for record in bundle.records)
    assert bundle.eligible is True
    assert bundle.blocker is None
    assert candidate_testnet_bundle_identity_ok(manifest, bundle.records) is True

    public = bundle.to_public_payload()
    assert public["eligible"] is True
    assert public["manifest"] == manifest.to_public_payload()
    assert len(public["records"]) == 4
    assert "api_key" not in str(public).lower()
    assert "api_secret" not in str(public).lower()


def test_candidate_testnet_evidence_bundle_preserves_owner_blocker_without_faking_eligibility():
    manifest = _manifest()
    bundle = build_candidate_testnet_evidence_bundle(
        manifest,
        smoke_evidence=_smoke(
            passed=False,
            status=LiveEvidenceStatus.CREDENTIALS_UNAVAILABLE,
        ),
        runtime_mode=RuntimeMode.TESTNET,
    )

    safety = {record.evidence_type: record for record in bundle.records}
    assert safety["risk_review"].passed is True
    assert safety["reconciliation_test"].passed is True
    assert safety["kill_switch_test"].passed is True
    assert safety["testnet_smoke"].passed is False
    assert bundle.eligible is False
    assert bundle.blocker == "BLOCKED_OWNER_INPUT"
    assert candidate_testnet_bundle_identity_ok(manifest, bundle.records) is False
