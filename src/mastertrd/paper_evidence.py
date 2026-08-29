from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class PaperStartReceipt:
    strategy_id: str
    genome_hash: str
    session_id: str
    venue: str
    engine: str
    engine_version: str
    connected: bool

    def __post_init__(self) -> None:
        identity = (
            self.strategy_id,
            self.genome_hash,
            self.session_id,
            self.venue,
            self.engine,
            self.engine_version,
        )
        if not all(identity):
            raise ValueError("paper start receipt identity fields are required")

    @property
    def receipt_hash(self) -> str:
        payload = {
            "strategy_id": self.strategy_id,
            "genome_hash": self.genome_hash,
            "session_id": self.session_id,
            "venue": self.venue,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "connected": self.connected,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def paper_started_evidence(
    candidate: StrategyGenome,
    receipt: PaperStartReceipt,
) -> ValidationEvidence:
    if receipt.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if receipt.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")

    passed = (
        receipt.engine == "nautilus_trader"
        and receipt.venue == "SANDBOX"
        and receipt.connected
    )
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="paper_started",
        dataset_hash=receipt.receipt_hash,
        code_hash=receipt.receipt_hash,
        engine=receipt.engine,
        engine_version=receipt.engine_version,
        passed=passed,
        metrics={"sandbox_connected": 1.0 if receipt.connected else 0.0},
    )
