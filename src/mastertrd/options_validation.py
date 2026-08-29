from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class OptionsStressPolicy:
    max_abs_delta_error: float
    max_abs_gamma_error: float
    max_abs_vega_error: float
    max_abs_theta_error: float
    max_surface_price_error_ratio: float
    max_surface_monotonicity_violations: int
    max_surface_convexity_violations: int
    min_surface_points: int

    def __post_init__(self) -> None:
        error_limits = (
            self.max_abs_delta_error,
            self.max_abs_gamma_error,
            self.max_abs_vega_error,
            self.max_abs_theta_error,
            self.max_surface_price_error_ratio,
        )
        if not all(isfinite(float(value)) for value in error_limits):
            raise ValueError("options stress thresholds must be finite")
        if any(value < 0.0 for value in error_limits):
            raise ValueError("options stress thresholds must be non-negative")
        if self.max_surface_price_error_ratio > 1.0:
            raise ValueError("max_surface_price_error_ratio must be at most 1")
        if self.max_surface_monotonicity_violations < 0 or self.max_surface_convexity_violations < 0:
            raise ValueError("surface violation limits cannot be negative")
        if self.min_surface_points <= 0:
            raise ValueError("min_surface_points must be positive")


@dataclass(frozen=True, slots=True)
class OptionsStressReport:
    strategy_id: str
    genome_hash: str
    dataset_hash: str
    code_hash: str
    engine: str
    engine_version: str
    delta_error: float
    gamma_error: float
    vega_error: float
    theta_error: float
    surface_points: int
    max_surface_price_error_ratio: float
    monotonicity_violations: int
    convexity_violations: int

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
            raise ValueError("options report identity fields are required")
        numeric = (
            self.delta_error,
            self.gamma_error,
            self.vega_error,
            self.theta_error,
            self.max_surface_price_error_ratio,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("options report numeric metrics must be finite")
        if self.surface_points < 0:
            raise ValueError("surface_points cannot be negative")
        if self.monotonicity_violations < 0 or self.convexity_violations < 0:
            raise ValueError("surface violations cannot be negative")
        if self.max_surface_price_error_ratio < 0.0:
            raise ValueError("max_surface_price_error_ratio cannot be negative")


def options_stress_evidence(
    candidate: StrategyGenome,
    report: OptionsStressReport,
    policy: OptionsStressPolicy,
) -> tuple[ValidationEvidence, ValidationEvidence]:
    if report.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if report.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")
    if candidate.family != "options":
        raise ValueError("options validation requires an options family candidate")
    if report.engine != "nautilus_trader":
        raise ValueError("options validation must come from nautilus_trader")

    delta_error = abs(float(report.delta_error))
    gamma_error = abs(float(report.gamma_error))
    vega_error = abs(float(report.vega_error))
    theta_error = abs(float(report.theta_error))

    greeks_passed = (
        delta_error <= policy.max_abs_delta_error
        and gamma_error <= policy.max_abs_gamma_error
        and vega_error <= policy.max_abs_vega_error
        and theta_error <= policy.max_abs_theta_error
    )
    surface_passed = (
        report.surface_points >= policy.min_surface_points
        and report.max_surface_price_error_ratio <= policy.max_surface_price_error_ratio
        and report.monotonicity_violations <= policy.max_surface_monotonicity_violations
        and report.convexity_violations <= policy.max_surface_convexity_violations
    )

    common = dict(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash=report.dataset_hash,
        code_hash=report.code_hash,
        engine=report.engine,
        engine_version=report.engine_version,
    )
    greeks = ValidationEvidence(
        **common,
        evidence_type="options_greeks_validation",
        passed=greeks_passed,
        metrics={
            "abs_delta_error": delta_error,
            "abs_gamma_error": gamma_error,
            "abs_vega_error": vega_error,
            "abs_theta_error": theta_error,
        },
    )
    surface = ValidationEvidence(
        **common,
        evidence_type="volatility_surface_stress",
        passed=surface_passed,
        metrics={
            "surface_points": float(report.surface_points),
            "max_surface_price_error_ratio": float(report.max_surface_price_error_ratio),
            "monotonicity_violations": float(report.monotonicity_violations),
            "convexity_violations": float(report.convexity_violations),
        },
    )
    return greeks, surface
