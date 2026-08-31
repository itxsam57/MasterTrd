from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .genome import StrategyGenome
from .live_readiness import live_evidence_bundle_identity_ok
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
