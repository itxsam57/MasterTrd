from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet

from .genome import StrategyGenome
from .strategy_families import DataLevel, family_spec


BASE_EVIDENCE: FrozenSet[str] = frozenset({
    "screen",
    "nautilus_backtest",
    "walk_forward",
    "cost_stress",
    "parameter_stability",
    "hidden_test",
    "regime_test",
    "paper_minimum_evidence",
})

HFT_EVIDENCE: FrozenSet[str] = frozenset({
    "hft_queue_model",
    "hft_feed_latency_stress",
    "hft_order_latency_stress",
    "spread_stress",
})


@dataclass(frozen=True, slots=True)
class ValidationProfile:
    family: str
    minimum_data_level: DataLevel
    required_evidence: FrozenSet[str]


def validation_profile(genome: StrategyGenome) -> ValidationProfile:
    spec = family_spec(genome.family)
    evidence = set(BASE_EVIDENCE)
    if spec.requires_hft_validation:
        evidence.update(HFT_EVIDENCE)
    if genome.family in {"stat_arb", "cross_venue_arb", "funding_basis", "delta_neutral"}:
        evidence.add("multi_leg_execution_stress")
    if genome.family == "options":
        evidence.update({"options_greeks_validation", "volatility_surface_stress"})
    return ValidationProfile(spec.key, spec.min_data_level, frozenset(evidence))
