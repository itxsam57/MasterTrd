from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class HftStressPolicy:
    min_completed_trades: int
    min_stressed_return: float
    max_queue_degradation: float
    max_feed_latency_degradation: float
    max_order_latency_degradation: float
    max_spread_degradation: float

    def __post_init__(self) -> None:
        if self.min_completed_trades <= 0:
            raise ValueError("min_completed_trades must be positive")
        numeric = (
            self.min_stressed_return,
            self.max_queue_degradation,
            self.max_feed_latency_degradation,
            self.max_order_latency_degradation,
            self.max_spread_degradation,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("HFT stress policy values must be finite")
        degradation_limits = numeric[1:]
        if not all(0.0 <= value <= 1.0 for value in degradation_limits):
            raise ValueError("HFT degradation limits must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class HftStressReport:
    strategy_id: str
    genome_hash: str
    dataset_hash: str
    code_hash: str
    engine_version: str
    queue_model: str
    baseline_return: float
    queue_model_return: float
    feed_latency_stress_return: float
    order_latency_stress_return: float
    spread_stress_return: float
    completed_trades: int

    def __post_init__(self) -> None:
        identity = (
            self.strategy_id,
            self.genome_hash,
            self.dataset_hash,
            self.code_hash,
            self.engine_version,
            self.queue_model,
        )
        if not all(identity):
            raise ValueError("HFT report identity fields and queue_model are required")
        metrics = (
            self.baseline_return,
            self.queue_model_return,
            self.feed_latency_stress_return,
            self.order_latency_stress_return,
            self.spread_stress_return,
        )
        if not all(isfinite(float(value)) for value in metrics):
            raise ValueError("HFT report returns must be finite")
        if self.completed_trades < 0:
            raise ValueError("completed_trades cannot be negative")


def _degradation(baseline: float, stressed: float) -> float:
    if baseline <= 0.0:
        return 0.0 if stressed >= baseline else 1.0
    return max(0.0, (baseline - stressed) / baseline)


def _dataset_hash(report: HftStressReport) -> str:
    encoded = json.dumps(asdict(report), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def hft_stress_evidence(
    candidate: StrategyGenome,
    report: HftStressReport,
    policy: HftStressPolicy,
) -> tuple[ValidationEvidence, ...]:
    if report.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if report.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")
    if not report.queue_model:
        raise ValueError("queue_model is required")

    common_pass = report.completed_trades >= policy.min_completed_trades
    dataset_hash = _dataset_hash(report)
    scenarios = (
        (
            "hft_queue_model",
            report.queue_model_return,
            policy.max_queue_degradation,
        ),
        (
            "hft_feed_latency_stress",
            report.feed_latency_stress_return,
            policy.max_feed_latency_degradation,
        ),
        (
            "hft_order_latency_stress",
            report.order_latency_stress_return,
            policy.max_order_latency_degradation,
        ),
        (
            "spread_stress",
            report.spread_stress_return,
            policy.max_spread_degradation,
        ),
    )

    records: list[ValidationEvidence] = []
    for evidence_type, stressed_return, max_degradation in scenarios:
        degradation = _degradation(report.baseline_return, stressed_return)
        passed = (
            common_pass
            and stressed_return >= policy.min_stressed_return
            and degradation <= max_degradation
        )
        records.append(
            ValidationEvidence(
                strategy_id=candidate.strategy_id,
                genome_hash=candidate.genome_hash,
                evidence_type=evidence_type,
                dataset_hash=dataset_hash,
                code_hash=report.code_hash,
                engine="hftbacktest",
                engine_version=report.engine_version,
                passed=passed,
                metrics={
                    "baseline_return": report.baseline_return,
                    "stressed_return": stressed_return,
                    "return_degradation": degradation,
                    "completed_trades": float(report.completed_trades),
                },
            )
        )
    return tuple(records)
