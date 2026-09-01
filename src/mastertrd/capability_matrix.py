from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


MANDATORY_V2_CAPABILITIES: tuple[str, ...] = (
    "family_coverage",
    "executable_strategy_semantics",
    "multileg_options_execution",
    "hft_execution",
    "risk_state_ownership",
    "persistent_runtime",
    "forward_paper_lifecycle",
    "specialist_research_brain",
    "candidate_bound_testnet_interface",
    "security",
    "reproducibility",
    "deployment_artifacts",
)


@dataclass(frozen=True, slots=True)
class CapabilityCheck:
    capability: str
    passed: bool
    evidence: str
    blocker: str | None = None

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise ValueError("capability is required")
        if self.passed:
            if not self.evidence.strip():
                raise ValueError("passing capability requires evidence")
            if self.blocker is not None:
                raise ValueError("passing capability cannot have a blocker")


def build_v2_capability_matrix(
    evidence: Mapping[str, str],
) -> tuple[CapabilityCheck, ...]:
    unknown = sorted(set(evidence) - set(MANDATORY_V2_CAPABILITIES))
    if unknown:
        raise ValueError(f"unknown V2 capability evidence: {', '.join(unknown)}")

    checks: list[CapabilityCheck] = []
    for capability in MANDATORY_V2_CAPABILITIES:
        receipt = str(evidence.get(capability, "")).strip()
        if receipt:
            checks.append(CapabilityCheck(capability, True, receipt, None))
        else:
            checks.append(
                CapabilityCheck(
                    capability,
                    False,
                    "",
                    "missing capability evidence",
                )
            )
    return tuple(checks)
