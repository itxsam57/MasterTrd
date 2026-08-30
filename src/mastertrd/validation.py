from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from math import isfinite
from typing import FrozenSet, Iterable, Mapping

from .contracts import EvaluationResult, StrategyState
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

# Promotion-grade HFT validation is intentionally a single evidence class bound
# to an integrity-checked historical L2 dataset. Synthetic stress evidence is
# retained for diagnostics but cannot satisfy promotion gates.
HFT_EVIDENCE: FrozenSet[str] = frozenset({"hft_real_l2"})


@dataclass(frozen=True, slots=True)
class ValidationProfile:
    family: str
    minimum_data_level: DataLevel
    required_evidence: FrozenSet[str]


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    strategy_id: str
    genome_hash: str
    evidence_type: str
    dataset_hash: str
    code_hash: str
    engine: str
    engine_version: str
    passed: bool
    metrics: Mapping[str, float] = field(default_factory=dict)
    supporting_only: bool = False

    def __post_init__(self) -> None:
        identity = (
            self.strategy_id,
            self.genome_hash,
            self.evidence_type,
            self.dataset_hash,
            self.code_hash,
            self.engine,
            self.engine_version,
        )
        if not all(identity):
            raise ValueError("validation evidence identity fields are required")
        if not all(isfinite(float(value)) for value in self.metrics.values()):
            raise ValueError("validation evidence metrics must be finite")

    @property
    def evidence_hash(self) -> str:
        payload = asdict(self)
        payload["metrics"] = {key: payload["metrics"][key] for key in sorted(payload["metrics"])}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def nautilus_backtest_evidence(result: EvaluationResult) -> ValidationEvidence:
    execution_score = float(result.scores.get("execution_backtest", 0.0))
    passed = (
        result.engine == "nautilus_trader"
        and result.trade_count > 0
        and execution_score > 0.0
    )
    return ValidationEvidence(
        strategy_id=result.strategy_id,
        genome_hash=result.genome_hash,
        evidence_type="nautilus_backtest",
        dataset_hash=result.dataset_hash,
        code_hash=result.code_hash,
        engine=result.engine,
        engine_version=result.engine_version,
        passed=passed,
        metrics={
            "total_return": result.total_return,
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "max_drawdown": result.max_drawdown,
            "profit_factor": result.profit_factor,
            "expectancy": result.expectancy,
            "trade_count": float(result.trade_count),
            "turnover": result.turnover,
            "fees": result.fees,
            "slippage": result.slippage,
            "execution_backtest": execution_score,
        },
    )


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


def validated_evidence_types(
    genome: StrategyGenome,
    records: Iterable[ValidationEvidence],
) -> frozenset[str]:
    accepted = {
        record.evidence_type
        for record in records
        if record.passed
        and not record.supporting_only
        and record.strategy_id == genome.strategy_id
        and record.genome_hash == genome.genome_hash
    }
    return frozenset(accepted)


def extra_evidence_for_target(genome: StrategyGenome, target: StrategyState) -> frozenset[str]:
    required: set[str] = set()
    spec = family_spec(genome.family)
    if target is StrategyState.ROBUST:
        if spec.requires_hft_validation:
            required.update(HFT_EVIDENCE)
        if genome.family in {"stat_arb", "cross_venue_arb", "funding_basis", "delta_neutral"}:
            required.add("multi_leg_execution_stress")
        if genome.family == "options":
            required.update({"options_greeks_validation", "volatility_surface_stress"})
    if target is StrategyState.HIDDEN_PASS:
        required.add("regime_test")
    return frozenset(required)
