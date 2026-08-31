from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral, Real

from .advanced_validation import (
    AdvancedValidationPolicy,
    monte_carlo_evidence,
    purged_cpcv_evidence,
)
from .asset_transfer import AssetTransferPolicy, asset_transfer_evidence
from .contracts import EvaluationResult, StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .nautilus_evaluation import run_nautilus_evaluation
from .robustness import (
    RobustnessPolicy,
    cost_stress_evidence,
    parameter_stability_evidence,
    walk_forward_evidence,
)
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class GeneratedRobustnessCycle:
    base_result: EvaluationResult
    stressed_result: EvaluationResult
    fold_results: tuple[EvaluationResult, ...]
    neighbor_results: tuple[EvaluationResult, ...]
    cpcv_results: tuple[EvaluationResult, ...]
    monte_carlo_results: tuple[EvaluationResult, ...]
    transfer_results: tuple[EvaluationResult, ...]
    evidence: tuple[ValidationEvidence, ...]
    promotion: PromotionDecision


def _candidate_with_section(
    candidate: StrategyGenome,
    section: str,
    values: dict[str, object],
) -> StrategyGenome:
    payload = {
        "strategy_id": candidate.strategy_id,
        "family": candidate.family,
        "style": candidate.style,
        "instruments": tuple(candidate.instruments),
        "timeframe": candidate.timeframe,
        "entry": dict(candidate.entry),
        "exit": dict(candidate.exit),
        "filters": dict(candidate.filters),
        "risk": dict(candidate.risk),
        "data_requirements": tuple(candidate.data_requirements),
        "allow_short": candidate.allow_short,
    }
    payload[section] = values
    return StrategyGenome(**payload)


def _semantic_neighbor_is_valid(candidate: StrategyGenome) -> bool:
    entry = candidate.entry
    fast_key = "fast_period" if "fast_period" in entry else "fast" if "fast" in entry else None
    slow_key = "slow_period" if "slow_period" in entry else "slow" if "slow" in entry else None
    if fast_key is not None and slow_key is not None:
        if float(entry[fast_key]) <= 0.0 or float(entry[slow_key]) <= 0.0:
            return False
        if float(entry[fast_key]) >= float(entry[slow_key]):
            return False
    for section in (candidate.entry, candidate.exit, candidate.risk):
        for key, value in section.items():
            if isinstance(value, bool) or not isinstance(value, Real):
                continue
            lowered = str(key).lower()
            if any(
                token in lowered
                for token in (
                    "period",
                    "window",
                    "lookback",
                    "ticks",
                    "levels",
                    "threshold",
                    "multiplier",
                    "ratio",
                    "atr",
                    "days",
                    "bps",
                    "inventory",
                    "fraction",
                    "drawdown",
                )
            ) and float(value) <= 0.0:
                return False
    return True


def _numeric_variants(value: Real) -> tuple[Real, ...]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        current = int(value)
        candidates = (current - 1, current + 1)
        return tuple(item for item in candidates if item > 0 and item != current)
    current = float(value)
    width = max(abs(current) * 0.05, 0.01)
    candidates = (current - width, current + width)
    if current > 0.0:
        candidates = tuple(item for item in candidates if item > 0.0)
    return tuple(item for item in candidates if item != current)


def _parameter_neighbors(
    candidate: StrategyGenome,
    *,
    max_neighbors: int = 4,
) -> tuple[StrategyGenome, ...]:
    """Build a small deterministic local neighborhood for any numeric genome."""
    if max_neighbors < 2:
        raise ValueError("max_neighbors must be at least two")

    neighbors: list[StrategyGenome] = []
    seen: set[str] = set()
    for section_name in ("entry", "exit", "filters", "risk"):
        section = dict(getattr(candidate, section_name))
        for key in sorted(section):
            value = section[key]
            if isinstance(value, bool) or not isinstance(value, Real):
                continue
            for variant in _numeric_variants(value):
                changed = dict(section)
                changed[key] = variant
                neighbor = _candidate_with_section(candidate, section_name, changed)
                if not _semantic_neighbor_is_valid(neighbor):
                    continue
                if neighbor.genome_hash == candidate.genome_hash or neighbor.genome_hash in seen:
                    continue
                seen.add(neighbor.genome_hash)
                neighbors.append(neighbor)
                if len(neighbors) >= max_neighbors:
                    return tuple(neighbors)

    if len(neighbors) < 2:
        raise ValueError("strategy parameter neighborhood is too small")
    return tuple(neighbors)


def _materialize_data(
    candidate: StrategyGenome,
    data_by_instrument: Mapping[str, Iterable[object]],
    *,
    label: str,
) -> dict[str, tuple[object, ...]]:
    expected = tuple(candidate.instruments)
    supplied = set(data_by_instrument)
    missing = [instrument_id for instrument_id in expected if instrument_id not in supplied]
    extras = sorted(supplied - set(expected))
    if missing:
        raise ValueError(f"{label} is missing instruments: {', '.join(missing)}")
    if extras:
        raise ValueError(f"{label} has unexpected instruments: {', '.join(extras)}")

    materialized: dict[str, tuple[object, ...]] = {}
    for instrument_id in expected:
        events = tuple(data_by_instrument[instrument_id])
        if not events:
            raise ValueError(f"{label} is empty for {instrument_id}")
        materialized[instrument_id] = events
    return materialized


def _canonical_primary_inputs(
    candidate: StrategyGenome,
    instruments: Mapping[str, object] | None,
    data_by_instrument: Mapping[str, Iterable[object]] | None,
    legacy_inputs: dict[str, object],
) -> tuple[Mapping[str, object], dict[str, tuple[object, ...]]]:
    if instruments is not None or data_by_instrument is not None:
        if instruments is None or data_by_instrument is None:
            raise ValueError("instruments and data_by_instrument must be supplied together")
        if legacy_inputs:
            raise TypeError("legacy single-instrument inputs cannot be mixed with generalized inputs")
        return instruments, _materialize_data(candidate, data_by_instrument, label="base robustness dataset")

    unknown = sorted(set(legacy_inputs) - {"instrument", "data"})
    if unknown:
        raise TypeError(f"unexpected robustness inputs: {', '.join(unknown)}")
    if set(legacy_inputs) != {"instrument", "data"}:
        raise ValueError("instruments and data_by_instrument are required")
    if len(candidate.instruments) != 1:
        raise ValueError("legacy single-instrument inputs cannot evaluate a multi-leg candidate")

    instrument = legacy_inputs["instrument"]
    instrument_id = candidate.instruments[0]
    observed_id = getattr(getattr(instrument, "id", None), "value", None)
    if observed_id != instrument_id:
        raise ValueError("legacy instrument does not match the candidate instrument")
    events = tuple(legacy_inputs["data"])
    if not events:
        raise ValueError("base robustness dataset is required")
    return {instrument_id: instrument}, {instrument_id: events}


def _canonical_dataset(
    candidate: StrategyGenome,
    payload: Mapping[str, Iterable[object]] | Iterable[object],
    *,
    label: str,
) -> dict[str, tuple[object, ...]]:
    if isinstance(payload, Mapping):
        return _materialize_data(candidate, payload, label=label)
    if len(candidate.instruments) != 1:
        raise ValueError(f"{label} must provide every multi-leg instrument")
    instrument_id = candidate.instruments[0]
    events = tuple(payload)
    if not events:
        raise ValueError(f"{label} is empty for {instrument_id}")
    return {instrument_id: events}


def _evaluate_datasets(
    *,
    candidate: StrategyGenome,
    instruments: Mapping[str, object],
    datasets: Sequence[tuple[str, Mapping[str, Iterable[object]]]],
    common: dict[str, object],
) -> tuple[EvaluationResult, ...]:
    results: list[EvaluationResult] = []
    for dataset_hash, payload in datasets:
        events = _canonical_dataset(candidate, payload, label=f"dataset {dataset_hash}")
        results.append(
            run_nautilus_evaluation(
                genome=candidate,
                instruments=instruments,
                data_by_instrument=events,
                dataset_hash=dataset_hash,
                **common,
            )
        )
    return tuple(results)


def run_generated_robustness_cycle(
    *,
    candidate: StrategyGenome,
    instruments: Mapping[str, object] | None = None,
    data_by_instrument: Mapping[str, Iterable[object]] | None = None,
    dataset_hash: str,
    fold_datasets: Sequence[tuple[str, Mapping[str, Iterable[object]]]],
    cpcv_datasets: Sequence[tuple[str, Mapping[str, Iterable[object]]]],
    monte_carlo_datasets: Sequence[tuple[str, Mapping[str, Iterable[object]]]],
    code_hash: str,
    trade_size: str,
    policy: RobustnessPolicy,
    advanced_policy: AdvancedValidationPolicy,
    stressed_fees: float,
    stressed_slippage: float,
    starting_balances: Sequence[str] = ("100000 USDT",),
    asset_transfer_datasets: Sequence[
        tuple[
            StrategyGenome,
            Mapping[str, object],
            str,
            Mapping[str, Iterable[object]],
        ]
    ] = (),
    asset_transfer_policy: AssetTransferPolicy | None = None,
    **legacy_inputs: object,
) -> GeneratedRobustnessCycle:
    resolved_instruments, base_events = _canonical_primary_inputs(
        candidate,
        instruments,
        data_by_instrument,
        legacy_inputs,
    )
    if not fold_datasets:
        raise ValueError("walk-forward fold datasets are required")
    if not cpcv_datasets:
        raise ValueError("purged/CPCV datasets are required")
    if not monte_carlo_datasets:
        raise ValueError("Monte Carlo datasets are required")
    if bool(asset_transfer_datasets) != (asset_transfer_policy is not None):
        raise ValueError("asset transfer datasets and policy must be supplied together")
    if stressed_fees <= 0.0 and stressed_slippage <= 0.0:
        raise ValueError("cost stress must increase fees or slippage")

    common: dict[str, object] = dict(
        code_hash=code_hash,
        trade_size_override=trade_size,
        starting_balances=starting_balances,
    )
    base_result = run_nautilus_evaluation(
        genome=candidate,
        instruments=resolved_instruments,
        data_by_instrument=base_events,
        dataset_hash=dataset_hash,
        **common,
    )
    stressed_result = run_nautilus_evaluation(
        genome=candidate,
        instruments=resolved_instruments,
        data_by_instrument=base_events,
        dataset_hash=dataset_hash,
        fees=stressed_fees,
        slippage=stressed_slippage,
        **common,
    )

    fold_results = _evaluate_datasets(
        candidate=candidate,
        instruments=resolved_instruments,
        datasets=fold_datasets,
        common=common,
    )

    neighbors = _parameter_neighbors(candidate)
    neighbor_results = tuple(
        run_nautilus_evaluation(
            genome=neighbor,
            instruments=resolved_instruments,
            data_by_instrument=base_events,
            dataset_hash=dataset_hash,
            **common,
        )
        for neighbor in neighbors
    )

    cpcv_results = _evaluate_datasets(
        candidate=candidate,
        instruments=resolved_instruments,
        datasets=cpcv_datasets,
        common=common,
    )
    monte_carlo_results = _evaluate_datasets(
        candidate=candidate,
        instruments=resolved_instruments,
        datasets=monte_carlo_datasets,
        common=common,
    )

    transfer_cases: tuple[tuple[StrategyGenome, EvaluationResult], ...] = ()
    if asset_transfer_datasets:
        transfer_common: dict[str, object] = dict(
            code_hash=code_hash,
            trade_size_override=trade_size,
            starting_balances=starting_balances,
        )
        cases: list[tuple[StrategyGenome, EvaluationResult]] = []
        for transfer_genome, raw_instruments, transfer_dataset_hash, raw_events in asset_transfer_datasets:
            if isinstance(raw_instruments, Mapping):
                transfer_instruments = raw_instruments
            else:
                if len(transfer_genome.instruments) != 1:
                    raise ValueError("legacy transfer instrument cannot represent a multi-leg transfer")
                transfer_instruments = {transfer_genome.instruments[0]: raw_instruments}
            transfer_events = _canonical_dataset(
                transfer_genome,
                raw_events,
                label=f"transfer dataset {transfer_dataset_hash}",
            )
            cases.append(
                (
                    transfer_genome,
                    run_nautilus_evaluation(
                        genome=transfer_genome,
                        instruments=transfer_instruments,
                        data_by_instrument=transfer_events,
                        dataset_hash=transfer_dataset_hash,
                        **transfer_common,
                    ),
                )
            )
        transfer_cases = tuple(cases)

    evidence_items: list[ValidationEvidence] = [
        walk_forward_evidence(candidate, fold_results, policy),
        cost_stress_evidence(candidate, base_result, stressed_result, policy),
        parameter_stability_evidence(candidate, base_result, neighbor_results, policy),
        purged_cpcv_evidence(candidate, cpcv_results, advanced_policy),
        monte_carlo_evidence(candidate, monte_carlo_results, advanced_policy),
    ]
    if transfer_cases and asset_transfer_policy is not None:
        evidence_items.append(asset_transfer_evidence(candidate, transfer_cases, asset_transfer_policy))
    evidence = tuple(evidence_items)

    promotion = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        candidate,
        evidence,
    )
    return GeneratedRobustnessCycle(
        base_result=base_result,
        stressed_result=stressed_result,
        fold_results=fold_results,
        neighbor_results=neighbor_results,
        cpcv_results=cpcv_results,
        monte_carlo_results=monte_carlo_results,
        transfer_results=tuple(result for _, result in transfer_cases),
        evidence=evidence,
        promotion=promotion,
    )
