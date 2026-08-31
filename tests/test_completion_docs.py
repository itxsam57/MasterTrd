from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
REPORT = ROOT / "docs" / "ACCEPTANCE_REPORT.md"


def test_checked_in_acceptance_snapshot_is_explicit_and_fail_closed() -> None:
    assert REPORT.is_file(), "missing checked-in acceptance snapshot"
    text = REPORT.read_text(encoding="utf-8")

    assert re.search(r"Source commit SHA: `[0-9a-f]{40}`", text)
    assert re.search(r"Lock SHA-256: `[0-9a-f]{64}`", text)
    assert "Implementation status: `PROCESS_READY`" in text
    assert "LIVE eligible: `false`" in text
    assert "Promotion Governor approved: `false`" in text

    for suite in (
        "locked_install",
        "cumulative_tests_and_coverage",
        "public_repo_safety",
        "clean_checkout",
    ):
        assert f"`{suite}` | `PASS`" in text

    for probe in ("risk_review", "reconciliation_test", "kill_switch_test"):
        assert f"`{probe}` | `PASS`" in text

    assert "`testnet_smoke` | `BLOCKED_OWNER_INPUT`" in text
    assert "exact-head workflow artifact" in text.lower()
    assert "checked-in snapshot" in text.lower()
    assert "LIVE remains disabled" in text


def test_readme_distinguishes_implementation_completion_from_live_activation() -> None:
    text = README.read_text(encoding="utf-8")
    lower = text.lower()

    assert "mastertrd is not yet complete" not in lower
    assert "implementation status" in lower
    assert "process_ready" in lower
    assert "docs/acceptance_report.md" in lower
    assert "blocked_owner_input" in lower
    assert "testnet" in lower
    assert "live" in lower
    assert "live_trading_enabled=false" in lower
    assert "promotion governor" in lower
