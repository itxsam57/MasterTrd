from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Iterable

from .genome import StrategyGenome
from .risk import RiskAction, RiskLimits, RiskSnapshot, evaluate_risk
from .validation import ValidationEvidence


_ENGINE = "mastertrd_safety"
_ENGINE_VERSION = "1"

LIVE_ELIGIBILITY_EVIDENCE = frozenset({
    "risk_review",
    "reconciliation_test",
    "kill_switch_test",
    "testnet_smoke",
})


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _base_snapshot(**changes) -> RiskSnapshot:
    values = {
        "order_notional": 1.0,
        "symbol_exposure": 0.0,
        "portfolio_exposure": 0.0,
        "daily_pnl": 0.0,
        "drawdown": 0.0,
        "orders_last_minute": 0,
        "data_stale": False,
        "reconciliation_ok": True,
        "emergency_stop": False,
    }
    values.update(changes)
    return RiskSnapshot(**values)


def _validate_live_limits(limits: RiskLimits) -> None:
    numeric = (
        limits.max_order_notional,
        limits.max_symbol_exposure,
        limits.max_portfolio_exposure,
        limits.max_daily_loss,
        limits.max_drawdown,
    )
    if any(value <= 0 for value in numeric):
        raise ValueError("live risk limits must be positive")
    if not (
        limits.max_order_notional
        <= limits.max_symbol_exposure
        <= limits.max_portfolio_exposure
    ):
        raise ValueError("live risk limit hierarchy must be order <= symbol <= portfolio")
    if limits.max_drawdown > 1.0:
        raise ValueError("max_drawdown must not exceed 1.0")


def risk_review_evidence(candidate: StrategyGenome, limits: RiskLimits) -> ValidationEvidence:
    _validate_live_limits(limits)

    probe_order = min(limits.max_order_notional, limits.max_symbol_exposure, limits.max_portfolio_exposure) / 2.0
    normal = evaluate_risk(limits, _base_snapshot(order_notional=probe_order))
    stale = evaluate_risk(limits, _base_snapshot(data_stale=True))
    reconciliation = evaluate_risk(limits, _base_snapshot(reconciliation_ok=False))
    daily_loss = evaluate_risk(limits, _base_snapshot(daily_pnl=-limits.max_daily_loss))
    drawdown = evaluate_risk(limits, _base_snapshot(drawdown=limits.max_drawdown))
    rate_limit = evaluate_risk(limits, _base_snapshot(orders_last_minute=limits.max_orders_per_minute))
    notional = evaluate_risk(limits, _base_snapshot(order_notional=limits.max_order_notional + 1.0))
    symbol = evaluate_risk(
        limits,
        _base_snapshot(
            order_notional=probe_order,
            symbol_exposure=limits.max_symbol_exposure,
        ),
    )
    portfolio = evaluate_risk(
        limits,
        _base_snapshot(
            order_notional=probe_order,
            portfolio_exposure=limits.max_portfolio_exposure,
        ),
    )
    manual_stop = evaluate_risk(limits, _base_snapshot(emergency_stop=True))

    metrics = {
        "normal_order_allowed": float(normal is RiskAction.ALLOW),
        "stale_data_system_kill": float(stale is RiskAction.KILL_SYSTEM),
        "reconciliation_system_kill": float(reconciliation is RiskAction.KILL_SYSTEM),
        "daily_loss_strategy_kill": float(daily_loss is RiskAction.KILL_STRATEGY),
        "drawdown_strategy_kill": float(drawdown is RiskAction.KILL_STRATEGY),
        "rate_limit_blocks": float(rate_limit is RiskAction.BLOCK_ORDER),
        "notional_limit_blocks": float(notional is RiskAction.BLOCK_ORDER),
        "symbol_exposure_blocks": float(symbol is RiskAction.BLOCK_ORDER),
        "portfolio_exposure_blocks": float(portfolio is RiskAction.BLOCK_ORDER),
        "manual_emergency_stop_system_kill": float(manual_stop is RiskAction.KILL_SYSTEM),
    }
    payload = {
        "limits": asdict(limits),
        "metrics": metrics,
    }
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="risk_review",
        dataset_hash=_hash_payload(payload),
        code_hash=candidate.genome_hash,
        engine=_ENGINE,
        engine_version=_ENGINE_VERSION,
        passed=all(value == 1.0 for value in metrics.values()),
        metrics=metrics,
    )


@dataclass(frozen=True, slots=True)
class ReconciliationTestReceipt:
    strategy_id: str
    genome_hash: str
    account_snapshot_id: str
    balances_match: bool
    positions_match: bool
    open_orders_match: bool
    fills_match: bool
    no_unexpected_orders: bool
    completed: bool

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.genome_hash or not self.account_snapshot_id:
            raise ValueError("reconciliation receipt identity fields are required")


def reconciliation_test_evidence(
    candidate: StrategyGenome,
    receipt: ReconciliationTestReceipt,
) -> ValidationEvidence:
    if receipt.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if receipt.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")

    checks = {
        "balances_match": float(receipt.balances_match),
        "positions_match": float(receipt.positions_match),
        "open_orders_match": float(receipt.open_orders_match),
        "fills_match": float(receipt.fills_match),
        "no_unexpected_orders": float(receipt.no_unexpected_orders),
        "completed": float(receipt.completed),
    }
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="reconciliation_test",
        dataset_hash=_hash_payload(asdict(receipt)),
        code_hash=candidate.genome_hash,
        engine=_ENGINE,
        engine_version=_ENGINE_VERSION,
        passed=all(value == 1.0 for value in checks.values()),
        metrics=checks,
    )


@dataclass(frozen=True, slots=True)
class KillSwitchTestReceipt:
    strategy_id: str
    genome_hash: str
    test_id: str
    manual_stop_verified: bool
    stale_data_kill_verified: bool
    reconciliation_failure_kill_verified: bool
    daily_loss_kill_verified: bool
    drawdown_kill_verified: bool
    completed: bool

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.genome_hash or not self.test_id:
            raise ValueError("kill-switch receipt identity fields are required")


def kill_switch_test_evidence(
    candidate: StrategyGenome,
    receipt: KillSwitchTestReceipt,
) -> ValidationEvidence:
    if receipt.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if receipt.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")

    checks = {
        "manual_stop_verified": float(receipt.manual_stop_verified),
        "stale_data_kill_verified": float(receipt.stale_data_kill_verified),
        "reconciliation_failure_kill_verified": float(receipt.reconciliation_failure_kill_verified),
        "daily_loss_kill_verified": float(receipt.daily_loss_kill_verified),
        "drawdown_kill_verified": float(receipt.drawdown_kill_verified),
        "completed": float(receipt.completed),
    }
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="kill_switch_test",
        dataset_hash=_hash_payload(asdict(receipt)),
        code_hash=candidate.genome_hash,
        engine=_ENGINE,
        engine_version=_ENGINE_VERSION,
        passed=all(value == 1.0 for value in checks.values()),
        metrics=checks,
    )


def live_evidence_bundle_identity_ok(
    candidate: StrategyGenome,
    records: Iterable[ValidationEvidence],
) -> bool:
    """Require one coherent code+dataset identity to cover every LIVE probe."""
    grouped: dict[tuple[str, str], set[str]] = {}
    for record in records:
        if (
            not record.passed
            or record.supporting_only
            or record.strategy_id != candidate.strategy_id
            or record.genome_hash != candidate.genome_hash
            or record.evidence_type not in LIVE_ELIGIBILITY_EVIDENCE
        ):
            continue
        identity = (record.code_hash, record.dataset_hash)
        grouped.setdefault(identity, set()).add(record.evidence_type)
    return any(LIVE_ELIGIBILITY_EVIDENCE.issubset(types) for types in grouped.values())
