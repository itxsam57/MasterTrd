from __future__ import annotations

from pathlib import Path

from mastertrd.acceptance import AcceptanceStatus, AcceptanceSuiteResult, run_full_acceptance
from mastertrd.capability_matrix import MANDATORY_V2_CAPABILITIES, CapabilityCheck


def _repo_fixture(tmp_path: Path) -> None:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("locked\n", encoding="utf-8")


def _passing_suites() -> tuple[AcceptanceSuiteResult, ...]:
    return (
        AcceptanceSuiteResult("locked_install", True, "pass"),
        AcceptanceSuiteResult("cumulative_tests_and_coverage", True, "pass"),
        AcceptanceSuiteResult("public_repo_safety", True, "pass"),
        AcceptanceSuiteResult("clean_checkout", True, "pass"),
    )


def _v2_capability_checks() -> tuple[CapabilityCheck, ...]:
    return tuple(
        CapabilityCheck(capability, True, f"verified:{capability}", None)
        for capability in MANDATORY_V2_CAPABILITIES
    )


def test_generic_green_suites_and_dataset_fixtures_cannot_replace_v2_capability_matrix(
    tmp_path: Path,
) -> None:
    _repo_fixture(tmp_path)

    report = run_full_acceptance(
        tmp_path,
        commit_sha="a" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("deterministic_bar_fixture", "real_l2_integrity_fixture"),
        engine_versions={"python": "3.13", "nautilus-trader": "1.231.0"},
        probes=(),
    )

    assert report.implementation_status is AcceptanceStatus.FAILED
    assert "v2_capability_matrix" in report.missing_mandatory_capabilities


def test_full_v2_acceptance_requires_and_accepts_complete_capability_matrix(
    tmp_path: Path,
) -> None:
    _repo_fixture(tmp_path)

    report = run_full_acceptance(
        tmp_path,
        commit_sha="b" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("deterministic_bar_fixture", "real_l2_integrity_fixture"),
        engine_versions={"python": "3.13", "nautilus-trader": "1.231.0"},
        probes=(),
        capability_checks=_v2_capability_checks(),
    )

    assert report.implementation_status is AcceptanceStatus.PROCESS_READY
    assert report.missing_mandatory_capabilities == ()
    assert tuple(check.capability for check in report.capability_checks) == MANDATORY_V2_CAPABILITIES
