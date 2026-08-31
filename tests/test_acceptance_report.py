from __future__ import annotations

from pathlib import Path

from mastertrd.acceptance import (
    AcceptanceProbe,
    AcceptanceStatus,
    AcceptanceSuiteResult,
    ProbeStatus,
    main,
    run_full_acceptance,
    write_acceptance_markdown,
)


def _repo_fixture(tmp_path: Path) -> Path:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("locked\n", encoding="utf-8")
    return tmp_path


def _suites() -> tuple[AcceptanceSuiteResult, ...]:
    return (
        AcceptanceSuiteResult("locked_install", True, "locked install passed"),
        AcceptanceSuiteResult("cumulative_tests_and_coverage", True, "tests and coverage passed"),
        AcceptanceSuiteResult("public_repo_safety", True, "security gate passed"),
        AcceptanceSuiteResult("clean_checkout", True, "fresh checkout passed"),
    )


def test_markdown_report_records_identity_status_and_owner_blocker(tmp_path: Path) -> None:
    root = _repo_fixture(tmp_path)
    probes = (
        AcceptanceProbe("risk_review", ProbeStatus.PASS, "passed"),
        AcceptanceProbe("reconciliation_test", ProbeStatus.PASS, "passed"),
        AcceptanceProbe("kill_switch_test", ProbeStatus.PASS, "passed"),
        AcceptanceProbe(
            "testnet_smoke",
            ProbeStatus.BLOCKED_OWNER_INPUT,
            "TESTNET credentials unavailable",
        ),
    )
    report = run_full_acceptance(
        root,
        commit_sha="a" * 40,
        suite_results=_suites(),
        dataset_fixtures=("deterministic_bar_fixture", "real_l2_integrity_fixture"),
        engine_versions={"python": "3.13", "nautilus-trader": "1.231.0"},
        probes=probes,
        promotion_governor_allowed=False,
    )
    output = tmp_path / "ACCEPTANCE_REPORT.md"

    written = write_acceptance_markdown(output, report)

    assert written == output
    text = output.read_text(encoding="utf-8")
    assert report.implementation_status is AcceptanceStatus.PROCESS_READY
    assert f"`{report.commit_sha}`" in text
    assert f"`{report.lock_hash}`" in text
    assert "Implementation status: `PROCESS_READY`" in text
    assert "LIVE eligible: `false`" in text
    assert "testnet_smoke" in text
    assert "BLOCKED_OWNER_INPUT" in text
    assert "LIVE remains disabled" in text


def test_markdown_cli_uses_verified_receipts_and_never_promotes_blocked_testnet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _repo_fixture(tmp_path)
    output = tmp_path / "ACCEPTANCE_REPORT.md"
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_LOCKED_INSTALL", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_CUMULATIVE_TESTS_AND_COVERAGE", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_PUBLIC_REPO_SAFETY", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_CLEAN_CHECKOUT", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_RISK_REVIEW", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_RECONCILIATION_TEST", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_KILL_SWITCH_TEST", "PASS")
    monkeypatch.setenv("MASTERTRD_ACCEPTANCE_TESTNET_SMOKE", "BLOCKED_OWNER_INPUT")
    monkeypatch.delenv("MASTERTRD_PROMOTION_GOVERNOR_ALLOWED", raising=False)

    exit_code = main([str(root), "--write", str(output)])

    assert exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert "Implementation status: `PROCESS_READY`" in text
    assert "LIVE eligible: `false`" in text
    assert "testnet_smoke" in text
    assert "BLOCKED_OWNER_INPUT" in text
    assert "b" * 40 in text
