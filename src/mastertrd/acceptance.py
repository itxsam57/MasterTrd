from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess

from .capability_matrix import (
    MANDATORY_V2_CAPABILITIES,
    CapabilityCheck,
    build_v2_capability_matrix,
)


MANDATORY_SUITES: tuple[str, ...] = (
    "locked_install",
    "cumulative_tests_and_coverage",
    "public_repo_safety",
    "clean_checkout",
)

MANDATORY_LIVE_EVIDENCE: tuple[str, ...] = (
    "risk_review",
    "reconciliation_test",
    "kill_switch_test",
    "testnet_smoke",
)

V2_DATASET_FIXTURES: frozenset[str] = frozenset(
    {
        "deterministic_bar_fixture",
        "real_l2_integrity_fixture",
    }
)


class AcceptanceStatus(StrEnum):
    PROCESS_READY = "PROCESS_READY"
    FAILED = "FAILED"


class ProbeStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_OWNER_INPUT = "BLOCKED_OWNER_INPUT"


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class AcceptanceSuiteResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class AcceptanceProbe:
    name: str
    status: ProbeStatus
    detail: str


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    commit_sha: str
    lock_hash: str
    implementation_status: AcceptanceStatus
    live_eligible: bool
    suites: tuple[AcceptanceSuiteResult, ...]
    dataset_fixtures: tuple[str, ...]
    engine_versions: tuple[tuple[str, str], ...]
    probes: tuple[AcceptanceProbe, ...]
    capability_checks: tuple[CapabilityCheck, ...]
    missing_mandatory_suites: tuple[str, ...]
    failed_mandatory_suites: tuple[str, ...]
    missing_mandatory_capabilities: tuple[str, ...]
    missing_live_evidence: tuple[str, ...]
    owner_input_blockers: tuple[str, ...]
    promotion_governor_allowed: bool
    static_checks: tuple[AcceptanceCheck, ...]


def run_static_acceptance(repo_root: Path) -> tuple[AcceptanceCheck, ...]:
    root = Path(repo_root)
    required = {
        "master_plan": root / "MASTER_PLAN.md",
        "dependency_lock": root / "uv.lock",
    }
    return tuple(
        AcceptanceCheck(name=name, passed=path.is_file(), detail=str(path))
        for name, path in required.items()
    )


def _lock_hash(repo_root: Path) -> str:
    path = Path(repo_root) / "uv.lock"
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _missing_v2_capabilities(
    capability_checks: tuple[CapabilityCheck, ...],
) -> tuple[str, ...]:
    if not capability_checks:
        return ("v2_capability_matrix",)

    by_capability = {check.capability: check for check in capability_checks}
    if len(by_capability) != len(capability_checks):
        return ("v2_capability_matrix",)

    return tuple(
        capability
        for capability in MANDATORY_V2_CAPABILITIES
        if capability not in by_capability or not by_capability[capability].passed
    )


def run_full_acceptance(
    repo_root: Path,
    *,
    commit_sha: str,
    suite_results: Iterable[AcceptanceSuiteResult],
    dataset_fixtures: Iterable[str],
    engine_versions: Mapping[str, str],
    probes: Iterable[AcceptanceProbe],
    capability_checks: Iterable[CapabilityCheck] = (),
    promotion_governor_allowed: bool = False,
) -> AcceptanceReport:
    root = Path(repo_root)
    static_checks = run_static_acceptance(root)
    suites = tuple(suite_results)
    probe_results = tuple(probes)
    capability_results = tuple(capability_checks)
    suite_by_name = {item.name: item for item in suites}
    probe_by_name = {item.name: item for item in probe_results}

    missing_mandatory_suites = tuple(
        name for name in MANDATORY_SUITES if name not in suite_by_name
    )
    failed_mandatory_suites = tuple(
        name
        for name in MANDATORY_SUITES
        if name in suite_by_name and not suite_by_name[name].passed
    )
    dataset_fixture_records = tuple(str(item) for item in dataset_fixtures)
    engine_version_records = tuple(
        sorted((str(name), str(version)) for name, version in engine_versions.items())
    )

    missing_capabilities: list[str] = []
    if not dataset_fixture_records:
        missing_capabilities.append("dataset_fixture_evidence")
    if V2_DATASET_FIXTURES.issubset(set(dataset_fixture_records)):
        missing_capabilities.extend(_missing_v2_capabilities(capability_results))
    missing_mandatory_capabilities = tuple(dict.fromkeys(missing_capabilities))

    static_passed = all(check.passed for check in static_checks)
    implementation_complete = (
        static_passed
        and not missing_mandatory_suites
        and not failed_mandatory_suites
        and not missing_mandatory_capabilities
    )

    missing_live_evidence = tuple(
        name
        for name in MANDATORY_LIVE_EVIDENCE
        if name not in probe_by_name or probe_by_name[name].status is not ProbeStatus.PASS
    )
    owner_input_blockers = tuple(
        probe.name
        for probe in probe_results
        if probe.status is ProbeStatus.BLOCKED_OWNER_INPUT
    )
    live_eligible = (
        implementation_complete
        and bool(promotion_governor_allowed)
        and not missing_live_evidence
    )

    return AcceptanceReport(
        commit_sha=str(commit_sha),
        lock_hash=_lock_hash(root),
        implementation_status=(
            AcceptanceStatus.PROCESS_READY
            if implementation_complete
            else AcceptanceStatus.FAILED
        ),
        live_eligible=live_eligible,
        suites=suites,
        dataset_fixtures=dataset_fixture_records,
        engine_versions=engine_version_records,
        probes=probe_results,
        capability_checks=capability_results,
        missing_mandatory_suites=missing_mandatory_suites,
        failed_mandatory_suites=failed_mandatory_suites,
        missing_mandatory_capabilities=missing_mandatory_capabilities,
        missing_live_evidence=missing_live_evidence,
        owner_input_blockers=owner_input_blockers,
        promotion_governor_allowed=bool(promotion_governor_allowed),
        static_checks=static_checks,
    )


def write_acceptance_json(
    output: Path,
    checks: Iterable[AcceptanceCheck],
) -> Path:
    path = Path(output)
    materialized = tuple(checks)
    payload = {
        "passed": all(check.passed for check in materialized),
        "checks": [asdict(check) for check in materialized],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_acceptance_markdown(output: Path, report: AcceptanceReport) -> Path:
    path = Path(output)
    lines = [
        "# MasterTrd Acceptance Report",
        "",
        f"- Source commit SHA: `{report.commit_sha}`",
        f"- Lock SHA-256: `{report.lock_hash}`",
        f"- Implementation status: `{report.implementation_status.value}`",
        f"- LIVE eligible: `{'true' if report.live_eligible else 'false'}`",
        f"- Promotion Governor approved: `{'true' if report.promotion_governor_allowed else 'false'}`",
        "",
        "## Mandatory suites",
        "",
        "| Suite | Result | Detail |",
        "| --- | --- | --- |",
    ]
    suite_by_name = {suite.name: suite for suite in report.suites}
    for name in MANDATORY_SUITES:
        suite = suite_by_name.get(name)
        if suite is None:
            lines.append(f"| `{name}` | `MISSING` | no verification receipt |")
        else:
            result = "PASS" if suite.passed else "FAIL"
            lines.append(f"| `{name}` | `{result}` | {_md_cell(suite.detail)} |")

    lines.extend(
        [
            "",
            "## V2 mandatory capability matrix",
            "",
            "| Capability | Result | Evidence | Blocker |",
            "| --- | --- | --- | --- |",
        ]
    )
    capability_by_name = {
        check.capability: check for check in report.capability_checks
    }
    for capability in MANDATORY_V2_CAPABILITIES:
        check = capability_by_name.get(capability)
        if check is None:
            lines.append(
                f"| `{capability}` | `MISSING` | none | missing capability evidence |"
            )
        else:
            result = "PASS" if check.passed else "FAIL"
            blocker = check.blocker or "none"
            evidence = check.evidence or "none"
            lines.append(
                f"| `{capability}` | `{result}` | {_md_cell(evidence)} | {_md_cell(blocker)} |"
            )

    lines.extend(["", "## Mandatory capability blockers", ""])
    if report.missing_mandatory_capabilities:
        lines.extend(
            f"- `{name}`: `MISSING`"
            for name in report.missing_mandatory_capabilities
        )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Live-eligibility evidence",
            "",
            "| Probe | Status | Detail |",
            "| --- | --- | --- |",
        ]
    )
    probe_by_name = {probe.name: probe for probe in report.probes}
    for name in MANDATORY_LIVE_EVIDENCE:
        probe = probe_by_name.get(name)
        if probe is None:
            lines.append(f"| `{name}` | `MISSING` | no probe receipt |")
        else:
            lines.append(
                f"| `{name}` | `{probe.status.value}` | {_md_cell(probe.detail)} |"
            )

    lines.extend(["", "## Dataset fixtures", ""])
    if report.dataset_fixtures:
        lines.extend(f"- `{item}`" for item in report.dataset_fixtures)
    else:
        lines.append("- none recorded")

    lines.extend(["", "## Engine versions", ""])
    if report.engine_versions:
        lines.extend(f"- `{name}`: `{version}`" for name, version in report.engine_versions)
    else:
        lines.append("- none recorded")

    lines.extend(["", "## Owner input blockers", ""])
    if report.owner_input_blockers:
        lines.extend(f"- `{name}`" for name in report.owner_input_blockers)
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Safety conclusion",
            "",
            "LIVE remains disabled by default. Process readiness does not activate LIVE trading. ",
            "A real TESTNET smoke, coherent live-evidence bundle, Promotion Governor approval, and deliberate owner-controlled LIVE configuration are still required before any LIVE activation.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _current_commit_sha(repo_root: Path) -> str:
    github_sha = os.environ.get("GITHUB_SHA", "").strip()
    if github_sha:
        return github_sha
    try:
        completed = subprocess.run(
            ["git", "-C", str(Path(repo_root)), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    value = completed.stdout.strip()
    return value or "UNKNOWN"


def _suite_receipt(name: str, env_name: str) -> AcceptanceSuiteResult:
    raw = os.environ.get(env_name, "").strip().upper()
    passed = raw == "PASS"
    detail = (
        f"verified by receipt {env_name}"
        if passed
        else f"verification receipt {env_name} unavailable or not PASS"
    )
    return AcceptanceSuiteResult(name, passed, detail)


def _probe_receipt(
    name: str,
    env_name: str,
    *,
    default: ProbeStatus = ProbeStatus.FAIL,
) -> AcceptanceProbe:
    raw = os.environ.get(env_name, "").strip().upper()
    try:
        status = ProbeStatus(raw) if raw else default
    except ValueError:
        status = ProbeStatus.FAIL
    detail = (
        f"verified by receipt {env_name}"
        if raw
        else (
            "owner-supplied TESTNET credentials/evidence unavailable"
            if status is ProbeStatus.BLOCKED_OWNER_INPUT
            else f"verification receipt {env_name} unavailable"
        )
    )
    return AcceptanceProbe(name, status, detail)


def _capability_matrix_from_environment() -> tuple[CapabilityCheck, ...]:
    env_names = {
        "family_coverage": "MASTERTRD_CAPABILITY_FAMILY_COVERAGE",
        "executable_strategy_semantics": "MASTERTRD_CAPABILITY_EXECUTABLE_STRATEGY_SEMANTICS",
        "multileg_options_execution": "MASTERTRD_CAPABILITY_MULTILEG_OPTIONS_EXECUTION",
        "hft_execution": "MASTERTRD_CAPABILITY_HFT_EXECUTION",
        "risk_state_ownership": "MASTERTRD_CAPABILITY_RISK_STATE_OWNERSHIP",
        "persistent_runtime": "MASTERTRD_CAPABILITY_PERSISTENT_RUNTIME",
        "forward_paper_lifecycle": "MASTERTRD_CAPABILITY_FORWARD_PAPER_LIFECYCLE",
        "specialist_research_brain": "MASTERTRD_CAPABILITY_SPECIALIST_RESEARCH_BRAIN",
        "candidate_bound_testnet_interface": "MASTERTRD_CAPABILITY_CANDIDATE_BOUND_TESTNET_INTERFACE",
        "security": "MASTERTRD_CAPABILITY_SECURITY",
        "reproducibility": "MASTERTRD_CAPABILITY_REPRODUCIBILITY",
        "deployment_artifacts": "MASTERTRD_CAPABILITY_DEPLOYMENT_ARTIFACTS",
    }
    evidence = {
        capability: f"verified by receipt {env_name}"
        for capability, env_name in env_names.items()
        if os.environ.get(env_name, "").strip().upper() == "PASS"
    }
    return build_v2_capability_matrix(evidence)


def _installed_engine_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in (
        "nautilus-trader",
        "hftbacktest",
        "vectorbt",
        "optuna",
        "pymoo",
        "duckdb",
        "pyarrow",
    ):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            continue
    return versions


def _report_from_environment(repo_root: Path) -> AcceptanceReport:
    suites = (
        _suite_receipt("locked_install", "MASTERTRD_ACCEPTANCE_LOCKED_INSTALL"),
        _suite_receipt(
            "cumulative_tests_and_coverage",
            "MASTERTRD_ACCEPTANCE_CUMULATIVE_TESTS_AND_COVERAGE",
        ),
        _suite_receipt(
            "public_repo_safety",
            "MASTERTRD_ACCEPTANCE_PUBLIC_REPO_SAFETY",
        ),
        _suite_receipt("clean_checkout", "MASTERTRD_ACCEPTANCE_CLEAN_CHECKOUT"),
    )
    probes = (
        _probe_receipt("risk_review", "MASTERTRD_ACCEPTANCE_RISK_REVIEW"),
        _probe_receipt(
            "reconciliation_test",
            "MASTERTRD_ACCEPTANCE_RECONCILIATION_TEST",
        ),
        _probe_receipt(
            "kill_switch_test",
            "MASTERTRD_ACCEPTANCE_KILL_SWITCH_TEST",
        ),
        _probe_receipt(
            "testnet_smoke",
            "MASTERTRD_ACCEPTANCE_TESTNET_SMOKE",
            default=ProbeStatus.BLOCKED_OWNER_INPUT,
        ),
    )
    governor_allowed = os.environ.get(
        "MASTERTRD_PROMOTION_GOVERNOR_ALLOWED", ""
    ).strip().lower() in {"1", "true", "yes"}
    return run_full_acceptance(
        repo_root,
        commit_sha=_current_commit_sha(repo_root),
        suite_results=suites,
        dataset_fixtures=(
            "deterministic_bar_fixture",
            "real_l2_integrity_fixture",
        ),
        engine_versions=_installed_engine_versions(),
        probes=probes,
        capability_checks=_capability_matrix_from_environment(),
        promotion_governor_allowed=governor_allowed,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MasterTrd plan-closure acceptance checks")
    parser.add_argument("repo_root", nargs="?", default=".")
    parser.add_argument("--write", default="artifacts/acceptance.json")
    args = parser.parse_args(argv)

    root = Path(args.repo_root)
    output = Path(args.write)
    if output.suffix.lower() in {".md", ".markdown"}:
        report = _report_from_environment(root)
        write_acceptance_markdown(output, report)
        return 0 if report.implementation_status is AcceptanceStatus.PROCESS_READY else 1

    checks = run_static_acceptance(root)
    write_acceptance_json(output, checks)
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
