from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "testnet-smoke.yml"


def test_testnet_workflow_lets_candidate_runner_emit_owner_blocker_without_credentials():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and len(jobs) == 1
    job = next(iter(jobs.values()))
    steps = job.get("steps")
    assert isinstance(steps, list) and steps

    names = [str(step.get("name", "")) for step in steps]
    assert "Require TESTNET credentials" not in names

    preflight = next(
        step for step in steps
        if step.get("name") == "Prove TESTNET-only runtime and credential preflight"
    )
    preflight_script = str(preflight.get("run", ""))
    assert "except ValueError" in preflight_script

    smoke_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Submit bounded Nautilus TESTNET smoke order"
    )
    upload_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Upload exact-SHA TESTNET evidence"
    )
    assert smoke_index < upload_index
    assert steps[upload_index].get("if") == "always()"
