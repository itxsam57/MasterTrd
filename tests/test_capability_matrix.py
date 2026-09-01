from __future__ import annotations

from mastertrd.capability_matrix import (
    MANDATORY_V2_CAPABILITIES,
    CapabilityCheck,
    build_v2_capability_matrix,
)


def test_v2_capability_matrix_represents_every_mandatory_plan_capability() -> None:
    evidence = {
        capability: f"verified:{capability}"
        for capability in MANDATORY_V2_CAPABILITIES
    }

    checks = build_v2_capability_matrix(evidence)

    assert tuple(check.capability for check in checks) == MANDATORY_V2_CAPABILITIES
    assert all(isinstance(check, CapabilityCheck) for check in checks)
    assert all(check.passed for check in checks)
    assert all(check.evidence.startswith("verified:") for check in checks)
    assert all(check.blocker is None for check in checks)


def test_v2_capability_matrix_fails_closed_when_required_evidence_is_missing() -> None:
    first = MANDATORY_V2_CAPABILITIES[0]

    checks = build_v2_capability_matrix({first: "verified:first"})
    by_capability = {check.capability: check for check in checks}

    assert by_capability[first].passed is True
    for capability in MANDATORY_V2_CAPABILITIES[1:]:
        check = by_capability[capability]
        assert check.passed is False
        assert check.evidence == ""
        assert check.blocker == "missing capability evidence"
