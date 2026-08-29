from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class MultiLegStressPolicy:
    min_completed_cycles: int
    max_leg_fill_skew: float
    max_residual_exposure_ratio: float
    max_slippage_bps: float

    def __post_init__(self) -> None:
        if self.min_completed_cycles <= 0:
            raise ValueError("min_completed_cycles must be positive")
        values = (
            self.max_leg_fill_skew,
            self.max_residual_exposure_ratio,
            self.max_slippage_bps,
        )
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("multi-leg policy thresholds must be finite")
        if not 0.0 <= self.max_leg_fill_skew <= 1.0:
            raise ValueError("max_leg_fill_skew must be between 0 and 1")
        if not 0.0 <= self.max_residual_exposure_ratio <= 1.0:
            raise ValueError("max_residual_exposure_ratio must be between 0 and 1")
        if self.max_slippage_bps < 0.0:
            raise ValueError("max_slippage_bps must be non-negative")


@dataclass(frozen=True, slots=True)
class MultiLegStressReport:
    strategy_id: str
    genome_hash: str
    dataset_hash: str
    code_hash: str
    engine: str
    engine_version: str
    expected_legs: int
    completed_cycles: int
    leg_fill_counts: Sequence[int]
    residual_exposure_ratio: float
    slippage_bps: float

    def __post_init__(self) -> None:
        identity = (
            self.strategy_id,
            self.genome_hash,
            self.dataset_hash,
            self.code_hash,
            self.engine,
            self.engine_version,
        )
        if not all(identity):
            raise ValueError("multi-leg report identity fields are required")
        if self.expected_legs < 2:
            raise ValueError("expected_legs must be at least 2")
        if len(self.leg_fill_counts) != self.expected_legs:
            raise ValueError("leg_fill_counts must match expected_legs")
        if self.completed_cycles < 0 or any(count < 0 for count in self.leg_fill_counts):
            raise ValueError("cycle and fill counts cannot be negative")
        if not isfinite(float(self.residual_exposure_ratio)) or not 0.0 <= self.residual_exposure_ratio <= 1.0:
            raise ValueError("residual_exposure_ratio must be finite and between 0 and 1")
        if not isfinite(float(self.slippage_bps)) or self.slippage_bps < 0.0:
            raise ValueError("slippage_bps must be finite and non-negative")


def _fill_skew(fill_counts: Sequence[int]) -> float:
    highest = max(fill_counts)
    if highest == 0:
        return 0.0
    return (highest - min(fill_counts)) / highest


def multi_leg_execution_stress_evidence(
    candidate: StrategyGenome,
    report: MultiLegStressReport,
    policy: MultiLegStressPolicy,
) -> ValidationEvidence:
    if report.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if report.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")
    if len(candidate.instruments) < 2:
        raise ValueError("multi-leg validation requires at least two candidate instruments")
    if report.expected_legs != len(candidate.instruments):
        raise ValueError("expected_legs does not match candidate instruments")
    if report.engine != "nautilus_trader":
        raise ValueError("multi-leg execution stress must come from nautilus_trader")

    fill_skew = _fill_skew(report.leg_fill_counts)
    minimum_fill_count = min(report.leg_fill_counts)
    minimum_fill_ratio = (
        minimum_fill_count / report.completed_cycles
        if report.completed_cycles > 0
        else 0.0
    )
    required_fill_ratio = 1.0 - policy.max_leg_fill_skew
    passed = (
        report.completed_cycles >= policy.min_completed_cycles
        and minimum_fill_count > 0
        and fill_skew <= policy.max_leg_fill_skew
        and minimum_fill_ratio >= required_fill_ratio
        and report.residual_exposure_ratio <= policy.max_residual_exposure_ratio
        and report.slippage_bps <= policy.max_slippage_bps
    )

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="multi_leg_execution_stress",
        dataset_hash=report.dataset_hash,
        code_hash=report.code_hash,
        engine=report.engine,
        engine_version=report.engine_version,
        passed=passed,
        metrics={
            "leg_count": float(report.expected_legs),
            "completed_cycles": float(report.completed_cycles),
            "minimum_leg_fill_count": float(minimum_fill_count),
            "minimum_leg_fill_ratio": float(minimum_fill_ratio),
            "leg_fill_skew": float(fill_skew),
            "residual_exposure_ratio": float(report.residual_exposure_ratio),
            "slippage_bps": float(report.slippage_bps),
        },
    )
