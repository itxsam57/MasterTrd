from __future__ import annotations

from collections.abc import Collection
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from math import isfinite
from numbers import Integral, Real
from typing import Any, Mapping, Sequence

from .advanced_validation import AdvancedValidationPolicy
from .asset_transfer import AssetTransferPolicy
from .contracts import MarketBar, StrategyState
from .genome import StrategyGenome
from .governor import evaluate_promotion, evaluate_validated_promotion
from .hidden_cycle import run_generated_hidden_cycle
from .hidden_gate import HiddenGatePolicy
from .holdout import chronological_holdout
from .memory_duckdb import DuckDbResearchMemory, ResearchStageReceipt
from .nautilus_data import market_bars_to_nautilus
from .nautilus_evaluation import run_binance_spot_evaluation
from .paper_cycle import start_generated_paper_cycle
from .research.evolve import evolve_genomes
from .research.optimize import optimize_genome
from .research.regimes import discover_regimes
from .research.screen import screen_genome
from .research_candidate_generation import (
    ResearchCandidateBatch,
    ResearchGenerationBlocker,
    generate_research_candidates,
)
from .robustness import RobustnessPolicy
from .robustness_cycle import run_generated_robustness_cycle
from .specialist_orchestrator import SpecialistInputs, run_specialist_gate
from .validation import ValidationEvidence, extra_evidence_for_target, nautilus_backtest_evidence


RESEARCH_STAGES: tuple[str, ...] = (
    "verified_data",
    "load_memory",
    "regime_discovery",
    "generation_mutation",
    "vectorbt_screen",
    "optuna_tune",
    "pymoo_evolution",
    "nautilus_validation",
    "specialist_tests",
    "hidden_robustness_stress",
    "store_outcomes",
    "queue_paper",
    "champion_challenger_rerank",
)


@dataclass(frozen=True, slots=True)
class ResearchBrainConfig:
    families: tuple[str, ...]
    instruments: tuple[str, ...]
    seed_start: int
    seed_stop: int
    screening_min_return: float
    optimization_trials: int
    evolution_generations: int
    evolution_population: int
    validation_budget: int
    paper_queue_cap: int
    hidden_fraction: float = 0.20
    trade_size: str = "0.01000"
    starting_balances: tuple[str, ...] = ("100000 USDT",)
    validation_window: int = 300
    fees: float = 0.0
    slippage: float = 0.0
    stressed_fees: float = 0.001
    stressed_slippage: float = 0.001
    robustness_policy: RobustnessPolicy = field(
        default_factory=lambda: RobustnessPolicy(
            min_trades_per_slice=1,
            min_profitable_slice_ratio=0.0,
            max_drawdown=0.99,
            min_stressed_return=-1.0,
            max_return_degradation=1.0,
            min_stable_neighbor_ratio=0.0,
        )
    )
    advanced_policy: AdvancedValidationPolicy = field(
        default_factory=lambda: AdvancedValidationPolicy(
            min_evaluations=1,
            min_trades_per_evaluation=1,
            min_positive_ratio=0.0,
            max_drawdown=0.99,
            min_monte_carlo_survival_ratio=0.0,
            max_monte_carlo_loss=-1.0,
        )
    )
    asset_transfer_policy: AssetTransferPolicy = field(
        default_factory=lambda: AssetTransferPolicy(
            min_transfer_assets=1,
            min_trades_per_asset=1,
            min_pass_ratio=1.0,
            min_total_return=-1.0,
            max_drawdown=0.99,
        )
    )
    hidden_policy: HiddenGatePolicy = field(
        default_factory=lambda: HiddenGatePolicy(
            min_trades_per_evaluation=1,
            min_total_return=-1.0,
            max_drawdown=0.99,
            min_regime_pass_ratio=0.0,
        )
    )

    def __post_init__(self) -> None:
        if not self.families or not self.instruments:
            raise ValueError("research families and instruments are required")
        if self.seed_stop <= self.seed_start:
            raise ValueError("seed_stop must be greater than seed_start")
        if self.optimization_trials <= 0:
            raise ValueError("optimization_trials must be positive")
        if self.evolution_generations <= 0 or self.evolution_population <= 1:
            raise ValueError("evolution budget must be positive")
        if self.validation_budget <= 0 or self.paper_queue_cap < 0:
            raise ValueError("validation budget must be positive and paper cap non-negative")
        if not 0.0 < self.hidden_fraction < 1.0:
            raise ValueError("hidden_fraction must be between zero and one")
        if self.validation_window < 50:
            raise ValueError("validation_window must be at least 50")
        numeric = (
            self.screening_min_return,
            self.fees,
            self.slippage,
            self.stressed_fees,
            self.stressed_slippage,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("research thresholds and costs must be finite")
        if self.fees < 0.0 or self.slippage < 0.0:
            raise ValueError("fees and slippage cannot be negative")
        if self.stressed_fees <= self.fees and self.stressed_slippage <= self.slippage:
            raise ValueError("stress costs must exceed base costs")
        if not self.trade_size or not self.starting_balances:
            raise ValueError("trade size and starting balances are required")

    @property
    def seed_count(self) -> int:
        return self.seed_stop - self.seed_start


@dataclass(frozen=True, slots=True)
class ResearchDataset:
    dataset_hash: str
    bars_by_instrument: Mapping[str, Sequence[MarketBar]]
    nautilus_instruments: Mapping[str, Any]
    available_data_levels: Mapping[str, Collection[object]] | None = None

    def __post_init__(self) -> None:
        if not self.dataset_hash:
            raise ValueError("dataset_hash is required")
        if not self.bars_by_instrument:
            raise ValueError("bars_by_instrument is required")
        if not self.nautilus_instruments:
            raise ValueError("nautilus_instruments is required")
        for key, bars in self.bars_by_instrument.items():
            if key not in self.nautilus_instruments:
                raise ValueError(f"missing Nautilus instrument for {key}")
            values = tuple(bars)
            if not values:
                raise ValueError(f"empty market dataset for {key}")
            previous = None
            for bar in values:
                if previous is not None and bar.timestamp <= previous:
                    raise ValueError(f"market bars are not strictly ordered for {key}")
                previous = bar.timestamp

        if self.available_data_levels is None:
            normalized_levels = {
                key: frozenset({"BAR"})
                for key in self.bars_by_instrument
            }
        else:
            normalized_levels: dict[str, frozenset[str]] = {}
            for key, values in self.available_data_levels.items():
                if key not in self.nautilus_instruments:
                    raise ValueError(f"missing Nautilus instrument for data levels {key}")
                normalized_levels[key] = frozenset(
                    str(getattr(value, "value", value)).upper()
                    for value in values
                )
        object.__setattr__(self, "available_data_levels", normalized_levels)


@dataclass(frozen=True, slots=True)
class ResearchFinalist:
    strategy_id: str
    genome_hash: str
    state: StrategyState
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchBrainReport:
    run_id: str
    generated: int
    stored: int
    paper_queued: int
    finalists: tuple[ResearchFinalist, ...]
    stage_receipts: tuple[ResearchStageReceipt, ...]
    resumed: bool = False


def _genome_payload(genome: StrategyGenome) -> dict[str, Any]:
    return genome.canonical_payload()


def _genome_from_payload(payload: Mapping[str, Any]) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=str(payload["strategy_id"]),
        family=str(payload["family"]),
        style=str(payload["style"]),
        instruments=tuple(str(item) for item in payload["instruments"]),
        timeframe=str(payload["timeframe"]),
        entry=dict(payload["entry"]),
        exit=dict(payload["exit"]),
        filters=dict(payload.get("filters", {})),
        risk=dict(payload.get("risk", {})),
        data_requirements=tuple(str(item) for item in payload.get("data_requirements", ("BAR",))),
        allow_short=bool(payload.get("allow_short", False)),
    )


def _run_id(
    config: ResearchBrainConfig,
    dataset: ResearchDataset,
    *,
    code_hash: str,
    lock_hash: str,
) -> str:
    payload = {
        "config": asdict(config),
        "dataset_hash": dataset.dataset_hash,
        "code_hash": code_hash,
        "lock_hash": lock_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _stage(
    memory: DuckDbResearchMemory,
    run_id: str,
    name: str,
    produce,
) -> tuple[Mapping[str, Any], bool]:
    existing = memory.get_stage(run_id, name)
    if existing is not None:
        return existing.artifact, True
    artifact = dict(produce())
    memory.record_stage(run_id=run_id, stage=name, artifact=artifact)
    return artifact, False


def _screen_evidence(
    genome: StrategyGenome,
    result,
    *,
    minimum_return: float,
) -> ValidationEvidence:
    return ValidationEvidence(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        evidence_type="screen",
        dataset_hash=result.dataset_hash,
        code_hash=result.code_hash,
        engine=result.engine,
        engine_version=result.engine_version,
        passed=result.total_return >= minimum_return,
        metrics={
            "total_return": float(result.total_return),
            "max_drawdown": float(result.max_drawdown),
            "trade_count": float(result.trade_count),
        },
    )


def evaluate_research_specialist_candidate(
    candidate: StrategyGenome,
    *,
    score: float,
    inputs: SpecialistInputs,
) -> dict[str, Any]:
    """Run the real specialist gate and persist its candidate-bound evidence payload."""
    result = run_specialist_gate(candidate, inputs)
    return {
        "genome": _genome_payload(candidate),
        "passed": bool(result.passed),
        "score": float(score),
        "reason": result.reason,
        "evidence": [asdict(record) for record in result.evidence],
        "missing_evidence": sorted(result.missing_evidence),
        "failed_evidence": sorted(result.failed_evidence),
    }



def run_research_specialist_stage(
    validated_outcomes: Sequence[Mapping[str, Any]],
    *,
    specialist_inputs_by_genome_hash: Mapping[str, SpecialistInputs],
) -> dict[str, Any]:
    """Route validated candidates through their candidate-bound specialist inputs."""
    outcomes: list[dict[str, Any]] = []
    for item in validated_outcomes:
        if not bool(item["passed"]):
            outcomes.append(dict(item))
            continue
        candidate = _genome_from_payload(item["genome"])
        inputs = specialist_inputs_by_genome_hash.get(
            candidate.genome_hash,
            SpecialistInputs(),
        )
        outcome = evaluate_research_specialist_candidate(
            candidate,
            score=float(item["score"]),
            inputs=inputs,
        )
        genome_payload = dict(outcome["genome"])
        genome_payload["genome_hash"] = candidate.genome_hash
        outcome["genome"] = genome_payload
        outcomes.append(outcome)
    return {"outcomes": outcomes}

def _parameter_space(genome: StrategyGenome) -> dict[str, object]:
    space: dict[str, object] = {}
    for key, value in genome.entry.items():
        if isinstance(value, bool) or not isinstance(value, Real):
            continue
        if isinstance(value, Integral):
            numeric = int(value)
            low = max(1, numeric - max(1, abs(numeric) // 4))
            high = max(low, numeric + max(1, abs(numeric) // 4))
            space[f"entry.{key}"] = (low, high)
        else:
            numeric = float(value)
            width = max(abs(numeric) * 0.20, 0.01)
            space[f"entry.{key}"] = (numeric - width, numeric + width)
    return space


def _valid_genome(genome: StrategyGenome) -> bool:
    entry = genome.entry
    fast_key = "fast" if "fast" in entry else "fast_period" if "fast_period" in entry else None
    slow_key = "slow" if "slow" in entry else "slow_period" if "slow_period" in entry else None
    if fast_key and slow_key:
        return float(entry[fast_key]) < float(entry[slow_key])
    return True


def _instrument_bars(dataset: ResearchDataset, key: str) -> tuple[MarketBar, ...]:
    if key not in dataset.bars_by_instrument:
        raise ValueError(f"dataset is missing configured instrument {key}")
    return tuple(dataset.bars_by_instrument[key])


def _score(genome: StrategyGenome, dataset: ResearchDataset, config: ResearchBrainConfig) -> float:
    result = screen_genome(
        genome,
        {key: _instrument_bars(dataset, key) for key in genome.instruments},
        fees=config.fees,
        slippage=config.slippage,
    )
    return float(result.total_return)


def _select_transfer_key(dataset: ResearchDataset, primary: str) -> str | None:
    return next((key for key in sorted(dataset.bars_by_instrument) if key != primary), None)


def _slice_hash(run_id: str, instrument: str, label: str, bars: Sequence[MarketBar]) -> str:
    identity = (
        run_id,
        instrument,
        label,
        str(bars[0].timestamp),
        str(bars[-1].timestamp),
        str(len(bars)),
    )
    return hashlib.sha256("|".join(identity).encode()).hexdigest()


def _restore_final_report(
    run_id: str,
    memory: DuckDbResearchMemory,
    artifact: Mapping[str, Any],
) -> ResearchBrainReport:
    finalists = tuple(
        ResearchFinalist(
            strategy_id=str(item["strategy_id"]),
            genome_hash=str(item["genome_hash"]),
            state=StrategyState(str(item["state"])),
            score=float(item["score"]),
            reason=str(item["reason"]),
        )
        for item in artifact.get("finalists", [])
    )
    return ResearchBrainReport(
        run_id=run_id,
        generated=int(artifact.get("generated", 0)),
        stored=int(artifact.get("stored", 0)),
        paper_queued=int(artifact.get("paper_queued", 0)),
        finalists=finalists,
        stage_receipts=tuple(memory.stage_receipts(run_id)),
        resumed=True,
    )


def run_research_brain(
    config: ResearchBrainConfig,
    dataset: ResearchDataset,
    memory: DuckDbResearchMemory,
    *,
    code_hash: str,
    lock_hash: str,
) -> ResearchBrainReport:
    """Run the approved autonomous research cycle without bypassing the Governor.

    Every stage has a durable idempotent receipt. A completed run returns directly
    from its final receipt; partially completed runs reconstruct candidate artifacts
    from the latest receipts and continue from the first missing stage.
    """
    if not code_hash or not lock_hash:
        raise ValueError("code_hash and lock_hash are required")
    run_id = _run_id(config, dataset, code_hash=code_hash, lock_hash=lock_hash)
    completed = memory.get_stage(run_id, RESEARCH_STAGES[-1])
    if completed is not None:
        return _restore_final_report(run_id, memory, completed.artifact)

    verified, _ = _stage(
        memory,
        run_id,
        "verified_data",
        lambda: {
            "dataset_hash": dataset.dataset_hash,
            "instrument_counts": {
                key: len(tuple(dataset.bars_by_instrument[key])) for key in sorted(dataset.bars_by_instrument)
            },
            "configured_present": all(key in dataset.bars_by_instrument for key in config.instruments),
            "code_hash": code_hash,
            "lock_hash": lock_hash,
        },
    )
    if not bool(verified["configured_present"]):
        raise ValueError("verified dataset is missing a configured instrument")

    _stage(
        memory,
        run_id,
        "load_memory",
        lambda: {"records_before": memory.count()},
    )

    def regimes_stage() -> Mapping[str, Any]:
        maps: dict[str, Any] = {}
        for key in config.instruments:
            bars = _instrument_bars(dataset, key)
            returns = [float(bars[index].close) / float(bars[index - 1].close) - 1.0 for index in range(1, len(bars))]
            evidence = discover_regimes(returns, min_size=5, penalty=5.0)
            maps[key] = {
                "dataset_hash": evidence.dataset_hash,
                "change_points": list(evidence.change_points),
                "observations": evidence.observations,
            }
        return {"regimes": maps}

    _stage(memory, run_id, "regime_discovery", regimes_stage)

    def generate_stage() -> Mapping[str, Any]:
        batch = generate_research_candidates(config, dataset)
        return {
            "genomes": [_genome_payload(genome) for genome in batch.candidates],
            "blockers": [asdict(blocker) for blocker in batch.blockers],
        }

    generated_artifact, _ = _stage(memory, run_id, "generation_mutation", generate_stage)
    generated = tuple(_genome_from_payload(item) for item in generated_artifact["genomes"])

    def screen_stage() -> Mapping[str, Any]:
        outcomes = []
        for genome in generated:
            try:
                result = screen_genome(
                    genome,
                    {key: _instrument_bars(dataset, key) for key in genome.instruments},
                    fees=config.fees,
                    slippage=config.slippage,
                )
                evidence = _screen_evidence(genome, result, minimum_return=config.screening_min_return)
                promotion = evaluate_validated_promotion(
                    StrategyState.IDEA,
                    StrategyState.SCREENED,
                    genome,
                    [evidence],
                )
                passed = bool(promotion.allowed)
                score = float(result.total_return)
                reason = promotion.reason
            except Exception as exc:
                passed = False
                score = -1.0
                reason = f"screen_failed:{type(exc).__name__}:{exc}"
            outcomes.append(
                {
                    "genome": _genome_payload(genome),
                    "passed": passed,
                    "score": score,
                    "reason": reason,
                }
            )
        return {"outcomes": outcomes}

    screen_artifact, _ = _stage(memory, run_id, "vectorbt_screen", screen_stage)

    def tune_stage() -> Mapping[str, Any]:
        outcomes = []
        for item in screen_artifact["outcomes"]:
            genome = _genome_from_payload(item["genome"])
            if not bool(item["passed"]):
                outcomes.append(dict(item))
                continue
            space = _parameter_space(genome)
            if not space:
                outcomes.append(dict(item))
                continue
            try:
                tuned = optimize_genome(
                    genome,
                    space,
                    lambda candidate: _score(candidate, dataset, config),
                    trials=config.optimization_trials,
                    seed=config.seed_start,
                    constraints=(_valid_genome,),
                )
                outcomes.append(
                    {
                        "genome": _genome_payload(tuned.best_genome),
                        "passed": True,
                        "score": float(tuned.best_scores[0]),
                        "reason": "optuna_tuned",
                    }
                )
            except Exception as exc:
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": False,
                        "score": float(item["score"]),
                        "reason": f"optimization_failed:{type(exc).__name__}:{exc}",
                    }
                )
        return {"outcomes": outcomes}

    tune_artifact, _ = _stage(memory, run_id, "optuna_tune", tune_stage)

    def evolve_stage() -> Mapping[str, Any]:
        outcomes = []
        for generated_item, tuned_item in zip(screen_artifact["outcomes"], tune_artifact["outcomes"], strict=True):
            genome = _genome_from_payload(tuned_item["genome"])
            if not bool(tuned_item["passed"]):
                outcomes.append(dict(tuned_item))
                continue
            original = _genome_from_payload(generated_item["genome"])
            try:
                evolved = evolve_genomes(
                    (genome, replace(original, timeframe=genome.timeframe)),
                    lambda candidate: _score(candidate, dataset, config),
                    generations=config.evolution_generations,
                    population=config.evolution_population,
                    seed=config.seed_start,
                )
                best = evolved[0]
                outcomes.append(
                    {
                        "genome": _genome_payload(best),
                        "passed": True,
                        "score": _score(best, dataset, config),
                        "reason": "pymoo_evolved",
                    }
                )
            except Exception as exc:
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": False,
                        "score": float(tuned_item["score"]),
                        "reason": f"evolution_failed:{type(exc).__name__}:{exc}",
                    }
                )
        return {"outcomes": outcomes}

    evolve_artifact, _ = _stage(memory, run_id, "pymoo_evolution", evolve_stage)

    def validation_stage() -> Mapping[str, Any]:
        outcomes = []
        admitted = 0
        for item in evolve_artifact["outcomes"]:
            genome = _genome_from_payload(item["genome"])
            if not bool(item["passed"]):
                outcomes.append(dict(item))
                continue
            if admitted >= config.validation_budget:
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": False,
                        "score": float(item["score"]),
                        "reason": "validation_budget_exhausted",
                    }
                )
                continue
            admitted += 1
            try:
                key = genome.instruments[0]
                bars = _instrument_bars(dataset, key)
                research, _hidden, _manifest = chronological_holdout(
                    bars,
                    hidden_fraction=config.hidden_fraction,
                    min_research=config.validation_window * 4,
                    min_hidden=config.validation_window,
                    dataset_hash=f"{dataset.dataset_hash}:{key}",
                )
                base = research[: config.validation_window]
                instrument = dataset.nautilus_instruments[key]
                events = market_bars_to_nautilus(base, instrument=instrument)
                result = run_binance_spot_evaluation(
                    genome=genome,
                    instrument=instrument,
                    data=events,
                    dataset_hash=_slice_hash(run_id, key, "backtest", base),
                    code_hash=code_hash,
                    trade_size_override=config.trade_size,
                    starting_balances=config.starting_balances,
                    fees=config.fees,
                    slippage=config.slippage,
                )
                evidence = nautilus_backtest_evidence(result)
                promotion = evaluate_validated_promotion(
                    StrategyState.SCREENED,
                    StrategyState.BACKTESTED,
                    genome,
                    [evidence],
                )
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": bool(promotion.allowed),
                        "score": float(result.total_return),
                        "reason": promotion.reason,
                    }
                )
            except Exception as exc:
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": False,
                        "score": float(item["score"]),
                        "reason": f"nautilus_validation_failed:{type(exc).__name__}:{exc}",
                    }
                )
        return {"outcomes": outcomes}

    validation_artifact, _ = _stage(memory, run_id, "nautilus_validation", validation_stage)

    def specialist_stage() -> Mapping[str, Any]:
        outcomes = []
        for item in validation_artifact["outcomes"]:
            genome = _genome_from_payload(item["genome"])
            if not bool(item["passed"]):
                outcomes.append(dict(item))
                continue
            extra = extra_evidence_for_target(genome, StrategyState.ROBUST)
            if extra:
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": False,
                        "score": float(item["score"]),
                        "reason": "specialist_evidence_required:" + ",".join(sorted(extra)),
                    }
                )
            else:
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "passed": True,
                        "score": float(item["score"]),
                        "reason": "standard_execution_path",
                    }
                )
        return {"outcomes": outcomes}

    specialist_artifact, _ = _stage(memory, run_id, "specialist_tests", specialist_stage)

    def robustness_stage() -> Mapping[str, Any]:
        outcomes = []
        for item in specialist_artifact["outcomes"]:
            genome = _genome_from_payload(item["genome"])
            if not bool(item["passed"]):
                terminal = evaluate_promotion(StrategyState.BACKTESTED, StrategyState.QUARANTINED, frozenset())
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "state": terminal.target.value,
                        "score": float(item["score"]),
                        "reason": str(item["reason"]),
                        "qualified_for_paper": False,
                    }
                )
                continue
            key = genome.instruments[0]
            transfer_key = _select_transfer_key(dataset, key)
            if transfer_key is None:
                terminal = evaluate_promotion(StrategyState.BACKTESTED, StrategyState.QUARANTINED, frozenset())
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "state": terminal.target.value,
                        "score": float(item["score"]),
                        "reason": "asset_transfer_dataset_unavailable",
                        "qualified_for_paper": False,
                    }
                )
                continue
            try:
                bars = _instrument_bars(dataset, key)
                research, hidden, manifest = chronological_holdout(
                    bars,
                    hidden_fraction=config.hidden_fraction,
                    min_research=config.validation_window * 4,
                    min_hidden=config.validation_window,
                    dataset_hash=f"{dataset.dataset_hash}:{key}",
                )
                w = config.validation_window
                windows = (research[0:w], research[w:2*w], research[2*w:3*w], research[3*w:4*w])
                if any(len(window) != w for window in windows):
                    raise ValueError("research dataset cannot supply all validation windows")
                instrument = dataset.nautilus_instruments[key]
                converted = tuple(market_bars_to_nautilus(window, instrument=instrument) for window in windows)
                transfer_instrument = dataset.nautilus_instruments[transfer_key]
                transfer_bars = _instrument_bars(dataset, transfer_key)[:w]
                transfer_events = market_bars_to_nautilus(transfer_bars, instrument=transfer_instrument)
                transfer_genome = replace(genome, instruments=(transfer_key,))

                robust = run_generated_robustness_cycle(
                    candidate=genome,
                    instruments={key: instrument},
                    data_by_instrument={key: converted[0]},
                    dataset_hash=_slice_hash(run_id, key, "robust-base", windows[0]),
                    fold_datasets=((_slice_hash(run_id, key, "fold", windows[1]), {key: converted[1]}),),
                    cpcv_datasets=((_slice_hash(run_id, key, "cpcv", windows[2]), {key: converted[2]}),),
                    monte_carlo_datasets=((_slice_hash(run_id, key, "mc", windows[3]), {key: converted[3]}),),
                    asset_transfer_datasets=((
                        transfer_genome,
                        {transfer_key: transfer_instrument},
                        _slice_hash(run_id, transfer_key, "transfer", transfer_bars),
                        {transfer_key: transfer_events},
                    ),),
                    code_hash=code_hash,
                    trade_size=config.trade_size,
                    policy=config.robustness_policy,
                    advanced_policy=config.advanced_policy,
                    asset_transfer_policy=config.asset_transfer_policy,
                    stressed_fees=config.stressed_fees,
                    stressed_slippage=config.stressed_slippage,
                    starting_balances=config.starting_balances,
                )
                if not robust.promotion.allowed:
                    raise RuntimeError("robustness promotion denied:" + ",".join(sorted(robust.promotion.missing_evidence)))

                hidden_events = market_bars_to_nautilus(hidden, instrument=instrument)
                hidden_cycle = run_generated_hidden_cycle(
                    candidate=genome,
                    instruments={key: instrument},
                    hidden_data_by_instrument={key: hidden_events},
                    manifest=manifest,
                    regime_datasets=(
                        (_slice_hash(run_id, key, "regime-a", windows[1]), {key: converted[1]}),
                        (_slice_hash(run_id, key, "regime-b", windows[2]), {key: converted[2]}),
                        (_slice_hash(run_id, key, "regime-c", windows[3]), {key: converted[3]}),
                    ),
                    code_hash=code_hash,
                    trade_size=config.trade_size,
                    policy=config.hidden_policy,
                    starting_balances=config.starting_balances,
                )
                if not hidden_cycle.promotion.allowed:
                    raise RuntimeError("hidden promotion denied:" + ",".join(sorted(hidden_cycle.promotion.missing_evidence)))
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "state": StrategyState.HIDDEN_PASS.value,
                        "score": float(hidden_cycle.hidden_result.total_return),
                        "reason": hidden_cycle.promotion.reason,
                        "qualified_for_paper": True,
                    }
                )
            except Exception as exc:
                terminal = evaluate_promotion(StrategyState.BACKTESTED, StrategyState.QUARANTINED, frozenset())
                outcomes.append(
                    {
                        "genome": _genome_payload(genome),
                        "state": terminal.target.value,
                        "score": float(item["score"]),
                        "reason": f"robustness_or_hidden_failed:{type(exc).__name__}:{exc}",
                        "qualified_for_paper": False,
                    }
                )
        return {"outcomes": outcomes}

    robustness_artifact, _ = _stage(memory, run_id, "hidden_robustness_stress", robustness_stage)

    def store_stage() -> Mapping[str, Any]:
        stored_ids = []
        for index, item in enumerate(robustness_artifact["outcomes"]):
            genome = _genome_from_payload(item["genome"])
            experiment_id = f"brain:{run_id}:{index}:{genome.strategy_id}"
            memory.append(
                experiment_id=experiment_id,
                genome=genome,
                status=str(item["state"]),
                engine="research_brain",
                score=float(item["score"]),
                reason=str(item["reason"]),
                metadata={
                    "run_id": run_id,
                    "dataset_hash": dataset.dataset_hash,
                    "code_hash": code_hash,
                    "lock_hash": lock_hash,
                    "qualified_for_paper": bool(item["qualified_for_paper"]),
                },
            )
            stored_ids.append(experiment_id)
        return {"stored_ids": stored_ids, "stored": len(stored_ids)}

    store_artifact, _ = _stage(memory, run_id, "store_outcomes", store_stage)

    def paper_stage() -> Mapping[str, Any]:
        qualified = [item for item in robustness_artifact["outcomes"] if bool(item["qualified_for_paper"])]
        qualified.sort(key=lambda item: (-float(item["score"]), str(item["genome"]["strategy_id"])))
        selected_hashes = {
            str(item["genome"]["genome_hash"]) if "genome_hash" in item["genome"] else _genome_from_payload(item["genome"]).genome_hash
            for item in qualified[: config.paper_queue_cap]
        }
        finalists = []
        queued = 0
        for item in robustness_artifact["outcomes"]:
            genome = _genome_from_payload(item["genome"])
            state = StrategyState(str(item["state"]))
            reason = str(item["reason"])
            if genome.genome_hash in selected_hashes:
                paper = start_generated_paper_cycle(
                    candidate=genome,
                    session_nonce=hashlib.sha256(f"{run_id}:{genome.genome_hash}".encode()).hexdigest()[:24],
                )
                if paper.promotion.allowed:
                    state = StrategyState.PAPER
                    reason = paper.promotion.reason
                    queued += 1
                else:
                    state = StrategyState.QUARANTINED
                    reason = paper.promotion.reason
            elif bool(item["qualified_for_paper"]):
                state = StrategyState.QUARANTINED
                reason = "paper_queue_cap_reached"
            finalists.append(
                {
                    "strategy_id": genome.strategy_id,
                    "genome_hash": genome.genome_hash,
                    "state": state.value,
                    "score": float(item["score"]),
                    "reason": reason,
                }
            )
        return {"paper_queued": queued, "finalists": finalists}

    paper_artifact, _ = _stage(memory, run_id, "queue_paper", paper_stage)

    def rerank_stage() -> Mapping[str, Any]:
        finalists = list(paper_artifact["finalists"])
        # Research score can order the paper queue and existing candidates, but it
        # cannot promote CHALLENGER/CHAMPION without their separate Governor evidence.
        finalists.sort(
            key=lambda item: (
                0 if item["state"] == StrategyState.PAPER.value else 1,
                -float(item["score"]),
                str(item["strategy_id"]),
            )
        )
        return {
            "generated": len(generated),
            "stored": int(store_artifact["stored"]),
            "paper_queued": int(paper_artifact["paper_queued"]),
            "finalists": finalists,
            "existing_challengers": [record.experiment_id for record in memory.by_status(StrategyState.CHALLENGER.value)],
            "existing_champions": [record.experiment_id for record in memory.by_status(StrategyState.CHAMPION.value)],
        }

    final_artifact, _ = _stage(memory, run_id, "champion_challenger_rerank", rerank_stage)
    finalists = tuple(
        ResearchFinalist(
            strategy_id=str(item["strategy_id"]),
            genome_hash=str(item["genome_hash"]),
            state=StrategyState(str(item["state"])),
            score=float(item["score"]),
            reason=str(item["reason"]),
        )
        for item in final_artifact["finalists"]
    )
    return ResearchBrainReport(
        run_id=run_id,
        generated=int(final_artifact["generated"]),
        stored=int(final_artifact["stored"]),
        paper_queued=int(final_artifact["paper_queued"]),
        finalists=finalists,
        stage_receipts=tuple(memory.stage_receipts(run_id)),
        resumed=False,
    )
