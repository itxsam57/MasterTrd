from __future__ import annotations

from pathlib import Path

import mastertrd.live_node as live_node
import mastertrd.nautilus_risk_hook as nautilus_risk_hook
from mastertrd.acceptance import (
    AcceptanceProbe,
    AcceptanceStatus,
    AcceptanceSuiteResult,
    ProbeStatus,
    run_full_acceptance,
)
from mastertrd.research_job import default_research_job_plan


ROOT = Path(__file__).resolve().parents[1]


def _passing_suites() -> tuple[AcceptanceSuiteResult, ...]:
    return (
        AcceptanceSuiteResult("locked_install", True, "locked install passed"),
        AcceptanceSuiteResult("cumulative_tests_and_coverage", True, "cumulative tests passed"),
        AcceptanceSuiteResult("public_repo_safety", True, "public repo safety passed"),
        AcceptanceSuiteResult("clean_checkout", True, "clean checkout passed"),
    )


def test_passed_implementation_with_owner_blocker_is_process_ready_not_complete(tmp_path: Path) -> None:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("locked\n", encoding="utf-8")

    report = run_full_acceptance(
        tmp_path,
        commit_sha="a" * 40,
        suite_results=_passing_suites(),
        dataset_fixtures=("deterministic_bar_fixture",),
        engine_versions={"python": "3.13"},
        probes=(
            AcceptanceProbe("risk_review", ProbeStatus.PASS, "passed"),
            AcceptanceProbe("reconciliation_test", ProbeStatus.PASS, "passed"),
            AcceptanceProbe("kill_switch_test", ProbeStatus.PASS, "passed"),
            AcceptanceProbe(
                "testnet_smoke",
                ProbeStatus.BLOCKED_OWNER_INPUT,
                "owner credentials unavailable",
            ),
        ),
        promotion_governor_allowed=False,
    )

    assert report.implementation_status is AcceptanceStatus.PROCESS_READY
    assert report.live_eligible is False
    assert report.owner_input_blockers == ("testnet_smoke",)


def test_obsolete_runtime_and_risk_compatibility_shims_are_removed() -> None:
    assert not hasattr(live_node, "load_execution_runtime_factory")
    assert not hasattr(nautilus_risk_hook, "default_nautilus_risk_limits")


def test_operator_docs_report_process_ready_and_owner_blocker_truthfully() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    report = (ROOT / "docs" / "ACCEPTANCE_REPORT.md").read_text(encoding="utf-8")

    assert "Implementation status: PROCESS_READY" in readme
    assert "BLOCKED_OWNER_INPUT" in readme
    assert "Implementation status: `PROCESS_READY`" in report
    assert "`testnet_smoke` | `BLOCKED_OWNER_INPUT`" in report
    assert "MASTERTRD_EXECUTION_FACTORY" not in operations


def test_scheduled_research_and_testnet_paths_are_repository_owned_and_fail_closed() -> None:
    plan = default_research_job_plan()
    assert len(plan.runnable_families) > 1
    blocked = {item.family: item.reason for item in plan.blocked_families}
    assert blocked["options"] == "qualifying_public_option_data_unavailable"
    assert blocked["market_making"] == "qualifying_public_l2_data_unavailable"

    research_workflow = (ROOT / ".github" / "workflows" / "autonomous-research.yml").read_text(
        encoding="utf-8"
    )
    testnet_workflow = (ROOT / ".github" / "workflows" / "testnet-smoke.yml").read_text(
        encoding="utf-8"
    )

    assert "uv run python -m mastertrd.research_job" in research_workflow
    assert "candidate_manifest_json" in testnet_workflow
    assert "BLOCKED_OWNER_INPUT" in testnet_workflow
    assert "testnet_candidate_bundle.json" in testnet_workflow


def test_v2_plan_checklist_is_closed_when_code_owned_capabilities_are_process_ready() -> None:
    plan = (
        ROOT / "docs" / "superpowers" / "plans" / "2026-08-31-mastertrd-v2-plan-closure.md"
    ).read_text(encoding="utf-8")

    assert "- [ ]" not in plan
    assert "Implementation status: `PROCESS_READY`" in plan
    assert "`testnet_smoke` remains `BLOCKED_OWNER_INPUT`" in plan
    assert "Completion Acceptance" in plan
