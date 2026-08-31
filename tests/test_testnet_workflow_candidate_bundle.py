from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "testnet-smoke.yml"


def test_testnet_workflow_builds_and_uploads_candidate_bound_eligibility_bundle():
    text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and len(jobs) == 1
    job = next(iter(jobs.values()))

    env = job.get("env")
    assert isinstance(env, dict)
    assert env.get("MASTERTRD_TESTNET_BUNDLE_PATH") == "artifacts/testnet_candidate_bundle.json"

    steps = job.get("steps")
    assert isinstance(steps, list) and steps
    names = [str(step.get("name", "")) for step in steps]
    smoke_index = names.index("Submit bounded Nautilus TESTNET smoke order")
    bundle_index = names.index("Build candidate-bound TESTNET evidence bundle")
    upload_index = names.index("Upload exact-SHA TESTNET evidence")
    assert smoke_index < bundle_index < upload_index

    bundle_step = steps[bundle_index]
    assert str(bundle_step.get("if", "")).lower() == "always()"
    script = str(bundle_step.get("run", ""))
    assert "build_candidate_testnet_evidence_bundle" in script
    assert "LiveValidationEvidence" in script
    assert "TestnetCandidateManifest" in script
    assert "BLOCKED_OWNER_INPUT" in script

    upload = steps[upload_index]
    upload_path = str(upload.get("with", {}).get("path", ""))
    assert "artifacts/testnet_candidate_bundle.json" in upload_path
