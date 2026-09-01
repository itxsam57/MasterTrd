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


def run_generated_hidden_cycle(
    *,
    candidate: StrategyGenome,
    instruments: Mapping[str, object],
    hidden_data_by_instrument: Mapping[str, Iterable[object]],
    manifest: HoldoutManifest,
    regime_datasets: Sequence[tuple[str, Mapping[str, Iterable[object]]]],
    code_hash: str,
    trade_size: str,
    policy: HiddenGatePolicy,
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> GeneratedHiddenCycle:
    hidden_events = _materialize_data(
        candidate,
        hidden_data_by_instrument,
        label="hidden dataset",
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
        instruments=instruments,
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
        regime_data = _materialize_data(
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
