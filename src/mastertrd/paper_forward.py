from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
from typing import Iterable

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class PaperForwardReport:
    strategy_id: str
    genome_hash: str
    session_id: str
    venue: str
    engine: str
    engine_version: str
    duration_seconds: int
    closed_trades: int
    total_return: float
    max_drawdown: float
    reconciliation_errors: int
    completed: bool

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
            raise ValueError("paper forward report identity fields are required")
        if self.duration_seconds < 0 or self.closed_trades < 0 or self.reconciliation_errors < 0:
            raise ValueError("paper forward counts cannot be negative")
        if not isfinite(float(self.total_return)) or not isfinite(float(self.max_drawdown)):
            raise ValueError("paper forward metrics must be finite")
        if self.total_return < -1.0:
            raise ValueError("total_return cannot be below -1")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ValueError("max_drawdown must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PaperMinimumPolicy:
    min_sessions: int
    min_duration_seconds: int
    min_closed_trades: int
    min_total_return: float
    max_drawdown: float

    def __post_init__(self) -> None:
        if self.min_sessions <= 0 or self.min_duration_seconds <= 0 or self.min_closed_trades <= 0:
            raise ValueError("paper minimum counts must be positive")
        if not isfinite(float(self.min_total_return)) or not isfinite(float(self.max_drawdown)):
            raise ValueError("paper minimum metrics must be finite")
        if self.min_total_return < -1.0:
            raise ValueError("min_total_return cannot be below -1")
        if not 0.0 <= self.max_drawdown <= 1.0:
            raise ValueError("max_drawdown must be between 0 and 1")


def _reports_hash(reports: list[PaperForwardReport]) -> str:
    payload = [asdict(report) for report in sorted(reports, key=lambda item: item.session_id)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def paper_minimum_evidence(
    candidate: StrategyGenome,
    reports: Iterable[PaperForwardReport],
    policy: PaperMinimumPolicy,
) -> ValidationEvidence:
    records = list(reports)
    session_ids = [record.session_id for record in records]
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("paper forward session_id values must be unique")

    for record in records:
        if record.strategy_id != candidate.strategy_id:
            raise ValueError("strategy_id does not match candidate")
        if record.genome_hash != candidate.genome_hash:
            raise ValueError("genome_hash does not match candidate")
        if record.engine != "nautilus_trader":
            raise ValueError("engine must be nautilus_trader")
        if record.venue != "SANDBOX":
            raise ValueError("venue must be SANDBOX")

    if records:
        engine_versions = {record.engine_version for record in records}
        if len(engine_versions) != 1:
            raise ValueError("engine_version must match across paper sessions")
        engine_version = records[0].engine_version
    else:
        engine_version = "1.231.0"

    duration_seconds = sum(record.duration_seconds for record in records)
    closed_trades = sum(record.closed_trades for record in records)
    reconciliation_errors = sum(record.reconciliation_errors for record in records)
    max_drawdown = max((record.max_drawdown for record in records), default=0.0)

    growth = 1.0
    for record in records:
        growth *= 1.0 + record.total_return
    total_return = growth - 1.0

    passed = (
        len(records) >= policy.min_sessions
        and duration_seconds >= policy.min_duration_seconds
        and closed_trades >= policy.min_closed_trades
        and total_return >= policy.min_total_return
        and max_drawdown <= policy.max_drawdown
        and reconciliation_errors == 0
        and all(record.completed for record in records)
    )

    report_hash = _reports_hash(records)
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="paper_minimum_evidence",
        dataset_hash=report_hash,
        code_hash=candidate.genome_hash,
        engine="nautilus_trader",
        engine_version=engine_version,
        passed=passed,
        metrics={
            "session_count": float(len(records)),
            "duration_seconds": float(duration_seconds),
            "closed_trades": float(closed_trades),
            "total_return": float(total_return),
            "max_drawdown": float(max_drawdown),
            "reconciliation_errors": float(reconciliation_errors),
            "completed_sessions": float(sum(1 for record in records if record.completed)),
        },
    )
