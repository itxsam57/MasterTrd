from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path


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


class AcceptanceStatus(StrEnum):
    COMPLETE = "COMPLETE"
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
    missing_mandatory_suites: tuple[str, ...]
    failed_mandatory_suites: tuple[str, ...]
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


def run_full_acceptance(
    repo_root: Path,
    *,
    commit_sha: str,
    suite_results: Iterable[AcceptanceSuiteResult],
    dataset_fixtures: Iterable[str],
    engine_versions: Mapping[str, str],
    probes: Iterable[AcceptanceProbe],
    promotion_governor_allowed: bool = False,
) -> AcceptanceReport:
    root = Path(repo_root)
    static_checks = run_static_acceptance(root)
    suites = tuple(suite_results)
    probe_results = tuple(probes)
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
    static_passed = all(check.passed for check in static_checks)
    implementation_complete = (
        static_passed
        and not missing_mandatory_suites
        and not failed_mandatory_suites
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
            AcceptanceStatus.COMPLETE
            if implementation_complete
            else AcceptanceStatus.FAILED
        ),
        live_eligible=live_eligible,
        suites=suites,
        dataset_fixtures=tuple(str(item) for item in dataset_fixtures),
        engine_versions=tuple(
            sorted((str(name), str(version)) for name, version in engine_versions.items())
        ),
        probes=probe_results,
        missing_mandatory_suites=missing_mandatory_suites,
        failed_mandatory_suites=failed_mandatory_suites,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MasterTrd completion acceptance checks")
    parser.add_argument("repo_root", nargs="?", default=".")
    parser.add_argument("--write", default="artifacts/acceptance.json")
    args = parser.parse_args(argv)

    checks = run_static_acceptance(Path(args.repo_root))
    write_acceptance_json(Path(args.write), checks)
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
