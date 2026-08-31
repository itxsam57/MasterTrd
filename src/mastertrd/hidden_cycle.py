from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .contracts import EvaluationResult, StrategyState
from .genome import StrategyGenome
from .governor import PromotionDecision, evaluate_validated_promotion
from .hidden_gate import HiddenGatePolicy, hidden_test_evidence, regime_test_evidence
from .holdout import HoldoutManifest
from .nautilus_evaluation import run_nautilus_evaluation
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class GeneratedHiddenCycle:
    hidden_result: EvaluationResult
    regime_results: tuple[EvaluationResult, ...]
    evidence: tuple[ValidationEvidence, ...]
    promotion: PromotionDecision


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
    hidden_data_by_instrument: Mapping[str, Iterable[object]] | None,
    legacy_inputs: dict[str, object],
) -> tuple[Mapping[str, object], dict[str, tuple[object, ...]]]:
    if instruments is not None or hidden_data_by_instrument is not None:
        if instruments is None or hidden_data_by_instrument is None:
            raise ValueError("instruments and hidden_data_by_instrument must be supplied together")
        if legacy_inputs:
            raise TypeError("legacy single-instrument inputs cannot be mixed with generalized inputs")
        return instruments, _materialize_data(
            candidate,
            hidden_data_by_instrument,
            label="hidden dataset",
        )

    unknown = sorted(set(legacy_inputs) - {"instrument", "hidden_data"})
    if unknown:
        raise TypeError(f"unexpected hidden-cycle inputs: {', '.join(unknown)}")
    if set(legacy_inputs) != {"instrument", "hidden_data"}:
        raise ValueError("instruments and hidden_data_by_instrument are required")
    if len(candidate.instruments) != 1:
        raise ValueError("legacy single-instrument inputs cannot evaluate a multi-leg candidate")

    instrument = legacy_inputs["instrument"]
    instrument_id = candidate.instruments[0]
    observed_id = getattr(getattr(instrument, "id", None), "value", None)
    if observed_id != instrument_id:
        raise ValueError("legacy instrument does not match the candidate instrument")
    events = tuple(legacy_inputs["hidden_data"])
    if not events:
        raise ValueError("hidden dataset is required")
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


def run_generated_hidden_cycle(
    *,
    candidate: StrategyGenome,
    instruments: Mapping[str, object] | None = None,
    hidden_data_by_instrument: Mapping[str, Iterable[object]] | None = None,
    manifest: HoldoutManifest,
    regime_datasets: Sequence[tuple[str, Mapping[str, Iterable[object]]]],
    code_hash: str,
    trade_size: str,
    policy: HiddenGatePolicy,
    starting_balances: Sequence[str] = ("100000 USDT",),
    **legacy_inputs: object,
) -> GeneratedHiddenCycle:
    resolved_instruments, hidden_events = _canonical_primary_inputs(
        candidate,
        instruments,
        hidden_data_by_instrument,
        legacy_inputs,
    )
    for instrument_id, events in hidden_events.items():
        if len(events) != manifest.hidden_count:
            raise ValueError(
                f"hidden data count must match frozen holdout manifest for {instrument_id}",
            )
    if not regime_datasets:
        raise ValueError("regime datasets are required")

    common = dict(
        genome=candidate,
        instruments=resolved_instruments,
        code_hash=code_hash,
        trade_size_override=trade_size,
        starting_balances=starting_balances,
    )
    hidden_result = run_nautilus_evaluation(
        data_by_instrument=hidden_events,
        dataset_hash=manifest.manifest_hash,
        **common,
    )

    regime_results: list[EvaluationResult] = []
    for regime_hash, raw_regime_data in regime_datasets:
        regime_data = _canonical_dataset(
            candidate,
            raw_regime_data,
            label=f"regime dataset {regime_hash}",
        )
        regime_results.append(
            run_nautilus_evaluation(
                data_by_instrument=regime_data,
                dataset_hash=regime_hash,
                **common,
            )
        )
    frozen_regime_results = tuple(regime_results)

    evidence = (
        hidden_test_evidence(candidate, hidden_result, manifest, policy),
        regime_test_evidence(candidate, frozen_regime_results, policy),
    )
    promotion = evaluate_validated_promotion(
        StrategyState.ROBUST,
        StrategyState.HIDDEN_PASS,
        candidate,
        evidence,
    )
    return GeneratedHiddenCycle(
        hidden_result=hidden_result,
        regime_results=frozen_regime_results,
        evidence=evidence,
        promotion=promotion,
    )
