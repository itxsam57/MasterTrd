from __future__ import annotations

import json
from pathlib import Path

from mastertrd.acceptance import (
    AcceptanceCheck,
    AcceptanceProbe,
    AcceptanceStatus,
    AcceptanceSuiteResult,
    ProbeStatus,
    main,
    run_full_acceptance,
    run_static_acceptance,
    write_acceptance_json,
)


def test_acceptance_check_is_immutable() -> None:
    check = AcceptanceCheck(name="master_plan", passed=True, detail="ok")
    assert check.name == "master_plan"
    assert check.passed is True
    assert check.detail == "ok"


def test_static_acceptance_requires_lock_and_master_plan(tmp_path: Path) -> None:
    checks = run_static_acceptance(tmp_path)
    by_name = {check.name: check for check in checks}

    assert by_name["master_plan"].passed is False
    assert by_name["dependency_lock"].passed is False


def test_static_acceptance_passes_when_required_files_exist(tmp_path: Path) -> None:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    checks = run_static_acceptance(tmp_path)
    by_name = {check.name: check for check in checks}

    assert by_name["master_plan"].passed is True
    assert by_name["dependency_lock"].passed is True


def test_write_acceptance_json_is_machine_readable(tmp_path: Path) -> None:
    output = tmp_path / "acceptance.json"
    checks = (
        AcceptanceCheck("master_plan", True, "MASTER_PLAN.md"),
        AcceptanceCheck("dependency_lock", False, "uv.lock"),
    )

    written = write_acceptance_json(output, checks)

    assert written == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "passed": False,
        "checks": [
            {"name": "master_plan", "passed": True, "detail": "MASTER_PLAN.md"},
            {"name": "dependency_lock", "passed": False, "detail": "uv.lock"},
        ],
    }


def test_acceptance_cli_writes_report_and_returns_success(tmp_path: Path) -> None:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    output = tmp_path / "out" / "acceptance.json"

    exit_code = main([str(tmp_path), "--write", str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True


def test_acceptance_cli_returns_failure_when_static_gate_fails(tmp_path: Path) -> None:
    output = tmp_path / "acceptance.json"

    exit_code = main([str(tmp_path), "--write", str(output)])

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is False


def _repo_fixture(tmp_path: Path) -> Path:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("locked\n", encoding="utf-8")
    return tmp_path


def _passing_suites() -> tuple[AcceptanceSuiteResult, ...]:
    return (
        AcceptanceSuiteResult("locked_install", True, "uv lock/sync/pip check passed"),
        AcceptanceSuiteResult("cumulative_tests_and_coverage", True, "all tests passed; coverage threshold passed"),
        AcceptanceSuiteResult("public_repo_safety", True, "secret/dependency gate passed"),
        AcceptanceSuiteResult("clean_checkout", True, "fresh checkout verification passed"),
    )


def test_full_acceptance_cannot_be_complete_when_a_mandatory_noncredential_gate_fails(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    suites = list(_passing_suites())
    suites[1] = AcceptanceSuiteResult(
        "cumulative_tests_and_coverage",
        False,
        "one cumulative test failed",
    )

    report = run_full_acceptance(
        root,
        commit_sha="a" * 40,
        suite_results=suites,
        dataset_fixtures=("deterministic_bar_fixture",),
        engine_versions={"python": "3.13"},
        probes=(),
    )

    assert report.implementation_status is AcceptanceStatus.FAILED
    assert report.live_eligible is False


def test_full_acceptance_requires_all_named_noncredential_proofs(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    report = run_full_acceptance(
        root,
        commit_sha="b" * 40,
        suite_results=_passing_suites()[:-1],
        dataset_fixtures=("deterministic_bar_fixture",),
        engine_versions={"python": "3.13"},
        probes=(),
    )

    assert report.implementation_status is AcceptanceStatus.FAILED
    assert "clean_checkout" in report.missing_mandatory_suites


def test_blocked_testnet_probe_is_owner_input_not_pass(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    report = run_full_acceptance(
        root,
        commit_sha="c" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("real_l2_integrity_fixture",),
        engine_versions={"python": "3.13", "nautilus-trader": "1.231.0"},
        probes=(
            AcceptanceProbe(
                "testnet_smoke",
                ProbeStatus.BLOCKED_OWNER_INPUT,
                "TESTNET credentials unavailable",
            ),
        ),
    )

    assert report.implementation_status is AcceptanceStatus.PROCESS_READY
    assert report.live_eligible is False
    assert report.owner_input_blockers == ("testnet_smoke",)
    probe = next(item for item in report.probes if item.name == "testnet_smoke")
    assert probe.status is ProbeStatus.BLOCKED_OWNER_INPUT
    assert probe.status is not ProbeStatus.PASS


def test_live_eligibility_requires_every_live_evidence_probe(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    partial = (
        AcceptanceProbe("risk_review", ProbeStatus.PASS, "passed"),
        AcceptanceProbe("reconciliation_test", ProbeStatus.PASS, "passed"),
        AcceptanceProbe("kill_switch_test", ProbeStatus.PASS, "passed"),
    )
    denied = run_full_acceptance(
        root,
        commit_sha="d" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("deterministic_bar_fixture",),
        engine_versions={"python": "3.13"},
        probes=partial,
        promotion_governor_allowed=True,
    )
    assert denied.live_eligible is False
    assert "testnet_smoke" in denied.missing_live_evidence

    complete = run_full_acceptance(
        root,
        commit_sha="e" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("deterministic_bar_fixture",),
        engine_versions={"python": "3.13"},
        probes=partial + (AcceptanceProbe("testnet_smoke", ProbeStatus.PASS, "real TESTNET smoke passed"),),
        promotion_governor_allowed=True,
    )
    assert complete.live_eligible is True


def test_live_evidence_names_are_not_enough_without_governor_approval(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    probes = tuple(
        AcceptanceProbe(name, ProbeStatus.PASS, "passed")
        for name in ("risk_review", "reconciliation_test", "kill_switch_test", "testnet_smoke")
    )
    report = run_full_acceptance(
        root,
        commit_sha="f" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("deterministic_bar_fixture",),
        engine_versions={"python": "3.13"},
        probes=probes,
        promotion_governor_allowed=False,
    )

    assert report.live_eligible is False
