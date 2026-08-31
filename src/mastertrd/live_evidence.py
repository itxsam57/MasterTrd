from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .genome import StrategyGenome
from .live_readiness import risk_review_evidence
from .reconciliation import ExecutionState, Reconciler
from .risk import RiskAction, RiskLimits, RiskSnapshot
from .risk_runtime import KillScope, OrderIntent, RiskRuntime
from .validation import ValidationEvidence


_ENGINE = "mastertrd_live_probe"
_ENGINE_VERSION = "1"


class LiveEvidenceStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WRONG_RUNTIME_MODE = "WRONG_RUNTIME_MODE"
    CREDENTIALS_UNAVAILABLE = "CREDENTIALS_UNAVAILABLE"
    PROBE_SKIPPED = "PROBE_SKIPPED"


@dataclass(frozen=True, slots=True)
class LiveValidationEvidence(ValidationEvidence):
    status: LiveEvidenceStatus = LiveEvidenceStatus.COMPLETED


def _require_identity(*, dataset_hash: str, code_hash: str) -> None:
    if not dataset_hash:
        raise ValueError("dataset_hash is required")
    if not code_hash:
        raise ValueError("code_hash is required")


def _evidence(
    candidate: StrategyGenome,
    *,
    evidence_type: str,
    dataset_hash: str,
    code_hash: str,
    passed: bool,
    status: LiveEvidenceStatus,
    metrics: Mapping[str, float],
) -> LiveValidationEvidence:
    _require_identity(dataset_hash=dataset_hash, code_hash=code_hash)
    return LiveValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type=evidence_type,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        engine=_ENGINE,
        engine_version=_ENGINE_VERSION,
        passed=passed,
        metrics=dict(metrics),
        supporting_only=False,
        status=status,
    )


def _wrong_mode(
    candidate: StrategyGenome,
    *,
    evidence_type: str,
    dataset_hash: str,
    code_hash: str,
) -> LiveValidationEvidence:
    return _evidence(
        candidate,
        evidence_type=evidence_type,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        passed=False,
        status=LiveEvidenceStatus.WRONG_RUNTIME_MODE,
        metrics={"testnet_mode": 0.0},
    )


def run_risk_review(
    candidate: StrategyGenome,
    *,
    limits: RiskLimits,
    dataset_hash: str,
    code_hash: str,
    runtime_mode: RuntimeMode,
) -> LiveValidationEvidence:
    _require_identity(dataset_hash=dataset_hash, code_hash=code_hash)
    if runtime_mode is not RuntimeMode.TESTNET:
        return _wrong_mode(
            candidate,
            evidence_type="risk_review",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
        )

    legacy = risk_review_evidence(candidate, limits)
    return _evidence(
        candidate,
        evidence_type="risk_review",
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        passed=legacy.passed,
        status=LiveEvidenceStatus.COMPLETED if legacy.passed else LiveEvidenceStatus.FAILED,
        metrics={**legacy.metrics, "testnet_mode": 1.0},
    )


def run_reconciliation_probe(
    candidate: StrategyGenome,
    *,
    engine_state: ExecutionState,
    venue_state: ExecutionState,
    fills_match: bool,
    no_unexpected_orders: bool,
    dataset_hash: str,
    code_hash: str,
    runtime_mode: RuntimeMode,
    reconciler: Reconciler | None = None,
) -> LiveValidationEvidence:
    _require_identity(dataset_hash=dataset_hash, code_hash=code_hash)
    if runtime_mode is not RuntimeMode.TESTNET:
        return _wrong_mode(
            candidate,
            evidence_type="reconciliation_test",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
        )

    active_reconciler = reconciler or Reconciler()
    result = active_reconciler.reconcile(engine_state, venue_state)
    metrics = {
        "state_reconciliation_ok": float(result.ok),
        "fills_match": float(bool(fills_match)),
        "no_unexpected_orders": float(bool(no_unexpected_orders)),
        "testnet_mode": 1.0,
    }
    passed = all(value == 1.0 for value in metrics.values())
    return _evidence(
        candidate,
        evidence_type="reconciliation_test",
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        passed=passed,
        status=LiveEvidenceStatus.COMPLETED if passed else LiveEvidenceStatus.FAILED,
        metrics=metrics,
    )


def run_kill_switch_probe(
    candidate: StrategyGenome,
    *,
    risk_runtime: RiskRuntime,
    intent: OrderIntent,
    snapshot: RiskSnapshot,
    submit_order: Callable[[OrderIntent], object],
    dataset_hash: str,
    code_hash: str,
    runtime_mode: RuntimeMode,
) -> LiveValidationEvidence:
    _require_identity(dataset_hash=dataset_hash, code_hash=code_hash)
    if runtime_mode is not RuntimeMode.TESTNET:
        return _wrong_mode(
            candidate,
            evidence_type="kill_switch_test",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
        )
    if intent.strategy_id != candidate.strategy_id:
        raise ValueError("order intent strategy_id does not match candidate")

    before = risk_runtime.check_order(intent, snapshot)
    pre_kill_allowed = before.action is RiskAction.ALLOW
    if pre_kill_allowed:
        submit_order(intent)

    risk_runtime.kill(KillScope.SYSTEM, "live evidence kill-switch probe")
    after = risk_runtime.check_order(intent, snapshot)
    post_kill_system_kill = after.action is RiskAction.KILL_SYSTEM

    # The submit callback is deliberately gated by the post-kill risk decision.
    # If this callback is ever reached after a kill, the probe fails by construction.
    post_kill_submission_blocked = after.action is not RiskAction.ALLOW
    if not post_kill_submission_blocked:
        submit_order(intent)

    metrics = {
        "pre_kill_allowed": float(pre_kill_allowed),
        "post_kill_system_kill": float(post_kill_system_kill),
        "post_kill_submission_blocked": float(post_kill_submission_blocked),
        "testnet_mode": 1.0,
    }
    passed = all(value == 1.0 for value in metrics.values())
    return _evidence(
        candidate,
        evidence_type="kill_switch_test",
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        passed=passed,
        status=LiveEvidenceStatus.COMPLETED if passed else LiveEvidenceStatus.FAILED,
        metrics=metrics,
    )


def run_testnet_smoke(
    candidate: StrategyGenome,
    *,
    environ: Mapping[str, str],
    dataset_hash: str,
    code_hash: str,
    runtime_mode: RuntimeMode,
    venue_minimum_notional: float,
    submit_test_order: Callable[[float], bool] | None,
) -> LiveValidationEvidence:
    _require_identity(dataset_hash=dataset_hash, code_hash=code_hash)
    minimum_notional = float(venue_minimum_notional)
    if not isfinite(minimum_notional) or minimum_notional <= 0.0:
        raise ValueError("venue_minimum_notional must be positive and finite")
    if runtime_mode is not RuntimeMode.TESTNET:
        return _wrong_mode(
            candidate,
            evidence_type="testnet_smoke",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
        )

    try:
        credentials = load_binance_credentials(RuntimeMode.TESTNET, environ)
    except ValueError:
        return _evidence(
            candidate,
            evidence_type="testnet_smoke",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
            passed=False,
            status=LiveEvidenceStatus.CREDENTIALS_UNAVAILABLE,
            metrics={
                "credentials_available": 0.0,
                "testnet_mode": 1.0,
                "order_submitted": 0.0,
                "submitted_notional": 0.0,
            },
        )

    if credentials is None:
        return _evidence(
            candidate,
            evidence_type="testnet_smoke",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
            passed=False,
            status=LiveEvidenceStatus.CREDENTIALS_UNAVAILABLE,
            metrics={
                "credentials_available": 0.0,
                "testnet_mode": 1.0,
                "order_submitted": 0.0,
                "submitted_notional": 0.0,
            },
        )
    if submit_test_order is None:
        return _evidence(
            candidate,
            evidence_type="testnet_smoke",
            dataset_hash=dataset_hash,
            code_hash=code_hash,
            passed=False,
            status=LiveEvidenceStatus.PROBE_SKIPPED,
            metrics={
                "credentials_available": 1.0,
                "testnet_mode": 1.0,
                "order_submitted": 0.0,
                "submitted_notional": 0.0,
            },
        )

    accepted = bool(submit_test_order(minimum_notional))
    metrics = {
        "credentials_available": 1.0,
        "testnet_mode": 1.0,
        "order_submitted": float(accepted),
        "submitted_notional": minimum_notional,
    }
    return _evidence(
        candidate,
        evidence_type="testnet_smoke",
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        passed=accepted,
        status=LiveEvidenceStatus.COMPLETED if accepted else LiveEvidenceStatus.FAILED,
        metrics=metrics,
    )
