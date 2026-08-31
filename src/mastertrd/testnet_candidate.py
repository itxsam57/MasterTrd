from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .contracts import RuntimeMode
from .genome import StrategyGenome
from .live_evidence import (
    LiveEvidenceStatus,
    run_kill_switch_probe,
    run_reconciliation_probe,
    run_risk_review,
)
from .live_readiness import live_evidence_bundle_identity_ok
from .reconciliation import ExecutionState
from .risk import RiskLimits, RiskSnapshot
from .risk_runtime import OrderIntent, RiskRuntime
from .validation import ValidationEvidence
from .venue import BinanceProduct


@dataclass(frozen=True, slots=True)
class TestnetCandidateManifest:
    candidate: StrategyGenome
    strategy_id: str
    genome_hash: str
    code_hash: str
    dataset_hash: str
    product: BinanceProduct
    probe_instrument: str
    order_notional_cap: Decimal

    def __post_init__(self) -> None:
        if not self.code_hash:
            raise ValueError("code_hash is required")
        if not self.dataset_hash:
            raise ValueError("dataset_hash is required")
        if self.strategy_id != self.candidate.strategy_id:
            raise ValueError("strategy_id does not match candidate")
        if self.genome_hash != self.candidate.genome_hash:
            raise ValueError("genome_hash does not match candidate")
        if self.probe_instrument not in self.candidate.instruments:
            raise ValueError("probe_instrument must belong to candidate")
        if not self.order_notional_cap.is_finite() or self.order_notional_cap <= 0:
            raise ValueError("order_notional_cap must be positive and finite")

    @classmethod
    def from_candidate(
        cls,
        candidate: StrategyGenome,
        *,
        code_hash: str,
        dataset_hash: str,
        product: BinanceProduct,
        probe_instrument: str,
        order_notional_cap: Decimal,
    ) -> "TestnetCandidateManifest":
        return cls(
            candidate=candidate,
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            code_hash=str(code_hash),
            dataset_hash=str(dataset_hash),
            product=BinanceProduct(product),
            probe_instrument=str(probe_instrument),
            order_notional_cap=Decimal(order_notional_cap),
        )

    def to_public_payload(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.canonical_payload(),
            "strategy_id": self.strategy_id,
            "genome_hash": self.genome_hash,
            "code_hash": self.code_hash,
            "dataset_hash": self.dataset_hash,
            "product": self.product.value,
            "probe_instrument": self.probe_instrument,
            "order_notional_cap": str(self.order_notional_cap),
        }

    @classmethod
    def from_public_payload(cls, payload: Mapping[str, Any]) -> "TestnetCandidateManifest":
        try:
            raw_candidate = payload["candidate"]
            if not isinstance(raw_candidate, Mapping):
                raise ValueError("candidate must be an object")
            candidate = StrategyGenome(
                strategy_id=str(raw_candidate["strategy_id"]),
                family=str(raw_candidate["family"]),
                style=str(raw_candidate["style"]),
                instruments=tuple(str(item) for item in raw_candidate["instruments"]),
                timeframe=str(raw_candidate["timeframe"]),
                entry=dict(raw_candidate["entry"]),
                exit=dict(raw_candidate["exit"]),
                filters=dict(raw_candidate.get("filters", {})),
                risk=dict(raw_candidate.get("risk", {})),
                data_requirements=tuple(
                    str(item) for item in raw_candidate.get("data_requirements", ("BAR",))
                ),
                allow_short=bool(raw_candidate.get("allow_short", False)),
            )
            product = BinanceProduct(str(payload["product"]))
            notional = Decimal(str(payload["order_notional_cap"]))
        except KeyError as exc:
            raise ValueError(f"missing candidate manifest field: {exc.args[0]}") from exc
        except (InvalidOperation, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(("missing candidate", "candidate must")):
                raise
            raise ValueError(f"invalid candidate manifest: {exc}") from exc

        return cls(
            candidate=candidate,
            strategy_id=str(payload.get("strategy_id", "")),
            genome_hash=str(payload.get("genome_hash", "")),
            code_hash=str(payload.get("code_hash", "")),
            dataset_hash=str(payload.get("dataset_hash", "")),
            product=product,
            probe_instrument=str(payload.get("probe_instrument", "")),
            order_notional_cap=notional,
        )


def candidate_testnet_bundle_identity_ok(
    manifest: TestnetCandidateManifest,
    records: Sequence[ValidationEvidence],
) -> bool:
    """Require promotion-grade live evidence to match the exact public candidate manifest."""
    manifest_bound = tuple(
        record
        for record in records
        if record.strategy_id == manifest.strategy_id
        and record.genome_hash == manifest.genome_hash
        and record.code_hash == manifest.code_hash
        and record.dataset_hash == manifest.dataset_hash
    )
    return live_evidence_bundle_identity_ok(manifest.candidate, manifest_bound)


@dataclass(frozen=True, slots=True)
class CandidateTestnetEvidenceBundle:
    manifest: TestnetCandidateManifest
    records: tuple[ValidationEvidence, ...]
    eligible: bool
    blocker: str | None = None

    def to_public_payload(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_public_payload(),
            "eligible": self.eligible,
            "blocker": self.blocker,
            "records": [asdict(record) for record in self.records],
        }


def _bundle_risk_limits(manifest: TestnetCandidateManifest) -> RiskLimits:
    cap = float(manifest.order_notional_cap)
    return RiskLimits(
        max_order_notional=cap,
        max_symbol_exposure=cap * 2.0,
        max_portfolio_exposure=cap * 5.0,
        max_daily_loss=cap * 2.0,
        max_drawdown=0.20,
        max_orders_per_minute=10,
    )


def _validate_smoke_identity(
    manifest: TestnetCandidateManifest,
    smoke_evidence: ValidationEvidence,
) -> None:
    if smoke_evidence.evidence_type != "testnet_smoke":
        raise ValueError("smoke evidence must have evidence_type testnet_smoke")
    expected = (
        manifest.strategy_id,
        manifest.genome_hash,
        manifest.code_hash,
        manifest.dataset_hash,
    )
    actual = (
        smoke_evidence.strategy_id,
        smoke_evidence.genome_hash,
        smoke_evidence.code_hash,
        smoke_evidence.dataset_hash,
    )
    if actual != expected:
        raise ValueError("smoke evidence identity does not match candidate manifest")


def build_candidate_testnet_evidence_bundle(
    manifest: TestnetCandidateManifest,
    *,
    smoke_evidence: ValidationEvidence,
    runtime_mode: RuntimeMode,
) -> CandidateTestnetEvidenceBundle:
    """Build one promotion bundle without manufacturing the external smoke result.

    The risk, reconciliation and kill-switch records are deterministic safety probes
    executed against the exact candidate/provenance identity. ``smoke_evidence`` is
    supplied by the real TESTNET runner and remains the external acceptance gate.
    """
    _validate_smoke_identity(manifest, smoke_evidence)
    limits = _bundle_risk_limits(manifest)
    candidate = manifest.candidate
    common = {
        "dataset_hash": manifest.dataset_hash,
        "code_hash": manifest.code_hash,
        "runtime_mode": runtime_mode,
    }

    risk_review = run_risk_review(candidate, limits=limits, **common)

    reconciliation_state = ExecutionState(
        account_id=f"testnet-probe:{manifest.genome_hash[:12]}",
        positions={},
        open_order_ids=frozenset(),
        balances={"USDT": "100000"},
    )
    reconciliation = run_reconciliation_probe(
        candidate,
        engine_state=reconciliation_state,
        venue_state=reconciliation_state,
        fills_match=True,
        no_unexpected_orders=True,
        **common,
    )

    risk_runtime = RiskRuntime(limits)
    intent = OrderIntent(
        strategy_id=manifest.strategy_id,
        symbol=manifest.probe_instrument,
        venue="BINANCE",
        side="BUY",
        quantity=1.0,
        order_type="MARKET",
    )
    cap = float(manifest.order_notional_cap)
    snapshot = RiskSnapshot(
        order_notional=cap / 2.0,
        symbol_exposure=0.0,
        portfolio_exposure=0.0,
        daily_pnl=0.0,
        drawdown=0.0,
        orders_last_minute=0,
        data_stale=False,
        reconciliation_ok=True,
        emergency_stop=False,
        venue_healthy=True,
    )
    local_submissions: list[OrderIntent] = []
    kill_switch = run_kill_switch_probe(
        candidate,
        risk_runtime=risk_runtime,
        intent=intent,
        snapshot=snapshot,
        submit_order=local_submissions.append,
        **common,
    )

    records: tuple[ValidationEvidence, ...] = (
        risk_review,
        reconciliation,
        kill_switch,
        smoke_evidence,
    )
    eligible = candidate_testnet_bundle_identity_ok(manifest, records)
    smoke_status = getattr(smoke_evidence, "status", None)
    blocker = None
    if not eligible:
        blocker = (
            "BLOCKED_OWNER_INPUT"
            if smoke_status is LiveEvidenceStatus.CREDENTIALS_UNAVAILABLE
            else "TESTNET_EVIDENCE_INCOMPLETE"
        )

    return CandidateTestnetEvidenceBundle(
        manifest=manifest,
        records=records,
        eligible=eligible,
        blocker=blocker,
    )
