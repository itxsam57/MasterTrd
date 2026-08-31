from __future__ import annotations

from dataclasses import dataclass

from .contracts import StrategyState
from .data.orderbook import OrderBookDataset
from .genome import StrategyGenome
from .hft_validation import HftLatencyProfile, validate_hft_candidate
from .multi_leg_validation import (
    MultiLegStressPolicy,
    MultiLegStressReport,
    multi_leg_execution_stress_evidence,
)
from .options_validation import OptionsStressPolicy, OptionsStressReport, options_stress_evidence
from .validation import ValidationEvidence, extra_evidence_for_target


@dataclass(frozen=True, slots=True)
class SpecialistInputs:
    multi_leg_report: MultiLegStressReport | None = None
    multi_leg_policy: MultiLegStressPolicy | None = None
    options_report: OptionsStressReport | None = None
    options_policy: OptionsStressPolicy | None = None
    hft_dataset: OrderBookDataset | None = None
    hft_latency_profile: HftLatencyProfile | None = None
    hft_queue_model: str | None = None


@dataclass(frozen=True, slots=True)
class SpecialistGateResult:
    passed: bool
    evidence: tuple[ValidationEvidence, ...]
    missing_evidence: frozenset[str]
    failed_evidence: frozenset[str]
    reason: str


def _reason(prefix: str, evidence_types: frozenset[str]) -> str:
    return prefix + ":" + ",".join(sorted(evidence_types))


def run_specialist_gate(
    candidate: StrategyGenome,
    inputs: SpecialistInputs,
) -> SpecialistGateResult:
    """Run the specialist evidence producers required by ``candidate``.

    The orchestrator never manufactures evidence. A required producer with missing
    typed inputs is reported as missing; a produced record which fails (or is only
    supporting evidence) is reported as failed. Candidate/report identity checks are
    delegated to the specialist validators themselves and therefore fail closed.
    """

    required = extra_evidence_for_target(candidate, StrategyState.ROBUST)
    if not required:
        return SpecialistGateResult(
            passed=True,
            evidence=(),
            missing_evidence=frozenset(),
            failed_evidence=frozenset(),
            reason="standard_execution_path",
        )

    evidence: list[ValidationEvidence] = []
    missing: set[str] = set()

    if "multi_leg_execution_stress" in required:
        if inputs.multi_leg_report is None or inputs.multi_leg_policy is None:
            missing.add("multi_leg_execution_stress")
        else:
            evidence.append(
                multi_leg_execution_stress_evidence(
                    candidate,
                    inputs.multi_leg_report,
                    inputs.multi_leg_policy,
                )
            )

    option_required = required & {
        "options_greeks_validation",
        "volatility_surface_stress",
    }
    if option_required:
        if inputs.options_report is None or inputs.options_policy is None:
            missing.update(option_required)
        else:
            evidence.extend(
                options_stress_evidence(
                    candidate,
                    inputs.options_report,
                    inputs.options_policy,
                )
            )

    if "hft_real_l2" in required:
        if (
            inputs.hft_dataset is None
            or inputs.hft_latency_profile is None
            or not inputs.hft_queue_model
        ):
            missing.add("hft_real_l2")
        else:
            evidence.append(
                validate_hft_candidate(
                    candidate,
                    inputs.hft_dataset,
                    latency_profile=inputs.hft_latency_profile,
                    queue_model=inputs.hft_queue_model,
                )
            )

    evidence_by_type = {record.evidence_type: record for record in evidence}
    missing.update(required - set(evidence_by_type) - missing)
    failed = frozenset(
        evidence_type
        for evidence_type in required
        if evidence_type in evidence_by_type
        and (
            not evidence_by_type[evidence_type].passed
            or evidence_by_type[evidence_type].supporting_only
        )
    )
    missing_evidence = frozenset(missing)

    if missing_evidence:
        return SpecialistGateResult(
            passed=False,
            evidence=tuple(evidence),
            missing_evidence=missing_evidence,
            failed_evidence=failed,
            reason=_reason("specialist_inputs_missing", missing_evidence),
        )
    if failed:
        return SpecialistGateResult(
            passed=False,
            evidence=tuple(evidence),
            missing_evidence=frozenset(),
            failed_evidence=failed,
            reason=_reason("specialist_evidence_failed", failed),
        )

    return SpecialistGateResult(
        passed=True,
        evidence=tuple(evidence),
        missing_evidence=frozenset(),
        failed_evidence=frozenset(),
        reason="specialist_evidence_passed",
    )
