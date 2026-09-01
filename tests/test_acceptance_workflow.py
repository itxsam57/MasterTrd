from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "acceptance.yml"


def test_acceptance_workflow_earns_receipts_and_writes_full_exact_head_report() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    assert workflow.get("permissions") == {"contents": "read"}

    upper = text.upper()
    assert "MASTERTRD_ACCEPTANCE_LOCKED_INSTALL=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_CUMULATIVE_TESTS_AND_COVERAGE=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_PUBLIC_REPO_SAFETY=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_CLEAN_CHECKOUT=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_RISK_REVIEW=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_RECONCILIATION_TEST=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_KILL_SWITCH_TEST=PASS" in upper
    assert "MASTERTRD_ACCEPTANCE_TESTNET_SMOKE: BLOCKED_OWNER_INPUT" in upper

    for receipt in (
        "MASTERTRD_CAPABILITY_FAMILY_COVERAGE=PASS",
        "MASTERTRD_CAPABILITY_EXECUTABLE_STRATEGY_SEMANTICS=PASS",
        "MASTERTRD_CAPABILITY_MULTILEG_OPTIONS_EXECUTION=PASS",
        "MASTERTRD_CAPABILITY_HFT_EXECUTION=PASS",
        "MASTERTRD_CAPABILITY_RISK_STATE_OWNERSHIP=PASS",
        "MASTERTRD_CAPABILITY_PERSISTENT_RUNTIME=PASS",
        "MASTERTRD_CAPABILITY_FORWARD_PAPER_LIFECYCLE=PASS",
        "MASTERTRD_CAPABILITY_SPECIALIST_RESEARCH_BRAIN=PASS",
        "MASTERTRD_CAPABILITY_CANDIDATE_BOUND_TESTNET_INTERFACE=PASS",
        "MASTERTRD_CAPABILITY_SECURITY=PASS",
        "MASTERTRD_CAPABILITY_REPRODUCIBILITY=PASS",
        "MASTERTRD_CAPABILITY_DEPLOYMENT_ARTIFACTS=PASS",
    ):
        assert receipt in upper

    assert "PIP-AUDIT" in upper
    assert "DETECT-SECRETS" in upper
    assert "EXCLUDE-FILES" in upper
    assert ".VENV" in upper
    assert "git grep -nEi -e " in text
    assert "GIT DIFF --EXIT-CODE" in upper
    assert "GIT REV-PARSE HEAD" in upper
    assert "GITHUB_SHA" in upper
    assert "ARTIFACTS/ACCEPTANCE_REPORT.MD" in upper
    assert "ARTIFACTS/ACCEPTANCE.JSON" in upper
    assert "--FULL-REPORT --WRITE ARTIFACTS/ACCEPTANCE.JSON" in upper
    assert "MASTERTRD.ACCEPTANCE . --WRITE ARTIFACTS/ACCEPTANCE_REPORT.MD || TRUE" not in upper
    assert "MASTERTRD.ACCEPTANCE . --FULL-REPORT --WRITE ARTIFACTS/ACCEPTANCE.JSON || TRUE" not in upper

    assert "LIVE_TRADING_ENABLED=TRUE" not in upper
    assert "MASTERTRD_MODE=LIVE" not in upper
    assert "BINANCE_LIVE" not in upper