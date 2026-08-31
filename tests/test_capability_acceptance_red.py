from pathlib import Path

from mastertrd.acceptance import AcceptanceStatus, AcceptanceSuiteResult, run_full_acceptance


def test_generic_green_suites_cannot_hide_missing_mandatory_capabilities(tmp_path: Path) -> None:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("locked\n", encoding="utf-8")
    suites = (
        AcceptanceSuiteResult("locked_install", True, "pass"),
        AcceptanceSuiteResult("cumulative_tests_and_coverage", True, "pass"),
        AcceptanceSuiteResult("public_repo_safety", True, "pass"),
        AcceptanceSuiteResult("clean_checkout", True, "pass"),
    )

    report = run_full_acceptance(
        tmp_path,
        commit_sha="a" * 40,
        suite_results=suites,
        dataset_fixtures=(),
        engine_versions={"python": "3.13"},
        probes=(),
    )

    assert report.implementation_status is AcceptanceStatus.FAILED
