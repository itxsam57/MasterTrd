from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> tuple[str, dict]:
    path = WORKFLOWS / name
    assert path.exists(), f"missing workflow: {name}"
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert isinstance(parsed, dict)
    return text, parsed


def _on(workflow: dict) -> dict:
    # PyYAML 1.1 may normalize the unquoted GitHub Actions key `on` to True.
    value = workflow.get("on", workflow.get(True, {}))
    assert isinstance(value, dict)
    return value


def _jobs(workflow: dict) -> dict:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and jobs
    return jobs


def test_autonomous_research_is_scheduled_public_safe_and_cancellable():
    text, workflow = _load("autonomous-research.yml")
    triggers = _on(workflow)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert workflow.get("permissions") == {"contents": "read"}
    assert workflow.get("concurrency", {}).get("cancel-in-progress") is True

    upper = text.upper()
    assert "LIVE_TRADING_ENABLED" not in upper
    assert "BINANCE_LIVE" not in upper
    assert "SECRETS." not in upper
    assert "UV LOCK --CHECK" in upper
    assert "UV SYNC --LOCKED" in upper or "UV SYNC --FROZEN" in upper
    assert "RESEARCHBRAIN" in upper or "MASTERTRD.RESEARCH_BRAIN" in upper or "MASTERTRD.RESEARCH_JOB" in upper
    assert "ACTIONS/UPLOAD-ARTIFACT" in upper


def test_autonomous_research_uploads_only_the_public_report():
    text, workflow = _load("autonomous-research.yml")
    jobs = _jobs(workflow)
    job = next(iter(jobs.values()))
    upload_steps = [
        step
        for step in job.get("steps", [])
        if str(step.get("uses", "")).lower().startswith("actions/upload-artifact@")
    ]

    assert len(upload_steps) == 1
    upload = upload_steps[0]
    assert upload.get("with", {}).get("path") == "artifacts/research/research-report.json"

    lower = text.lower()
    assert "artifacts/research/public-data" not in lower
    assert "research.duckdb" not in lower
    assert "secrets." not in lower


def test_testnet_smoke_is_environment_gated_and_never_live():
    text, workflow = _load("testnet-smoke.yml")
    assert workflow.get("permissions") == {"contents": "read"}
    jobs = _jobs(workflow)
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert job.get("environment") == "testnet"

    upper = text.upper()
    assert "MASTERTRD_MODE: TESTNET" in upper or "MASTERTRD_MODE=TESTNET" in upper
    assert "BINANCE_TESTNET_API_KEY" in upper
    assert "BINANCE_TESTNET_API_SECRET" in upper
    assert "BINANCE_TESTNET_ACCOUNT_ID" in upper
    assert "BINANCE_LIVE" not in upper
    assert "LIVE_TRADING_ENABLED" not in upper
    assert "WITHDRAWAL" in upper
    assert "EXIT 1" in upper
    assert "UV LOCK --CHECK" in upper
    assert "UV SYNC --LOCKED" in upper or "UV SYNC --FROZEN" in upper


def test_testnet_smoke_invokes_real_runner_and_uploads_evidence():
    text, _ = _load("testnet-smoke.yml")
    lower = text.lower()

    assert "python -m mastertrd.testnet_smoke" in lower
    assert "actions/upload-artifact" in lower
    assert "testnet_smoke.json" in lower


def test_existing_stack_workflows_keep_read_only_permissions_and_locked_installs():
    for name in ("research-stack.yml", "execution-stack.yml"):
        text, workflow = _load(name)
        assert workflow.get("permissions") == {"contents": "read"}
        upper = text.upper()
        assert "UV LOCK --CHECK" in upper
        assert "UV SYNC --LOCKED" in upper or "UV SYNC --FROZEN" in upper
        assert "PIP INSTALL -E" not in upper
        assert "LIVE_TRADING_ENABLED" not in upper


def test_scheduled_research_job_is_owned_by_research_stack_not_core_coverage():
    research_text, research_workflow = _load("research-stack.yml")
    triggers = _on(research_workflow)
    push_paths = set(triggers["push"]["paths"])
    pull_paths = set(triggers["pull_request"]["paths"])
    required_paths = {
        "src/mastertrd/research_job.py",
        ".github/workflows/autonomous-research.yml",
        "tests/test_research_job.py",
        "tests/test_workflow_policy.py",
    }
    assert required_paths <= push_paths
    assert required_paths <= pull_paths

    lower = research_text.lower()
    assert "tests/test_research_job.py" in lower
    assert "tests/test_workflow_policy.py" in lower

    core_text, _ = _load("ci.yml")
    assert "src/mastertrd/research_job.py" in core_text
