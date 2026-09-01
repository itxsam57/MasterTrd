from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import mastertrd.research_job as research_job
from mastertrd.strategy_universe import strategy_recipe


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "autonomous-research.yml"


def _workflow() -> dict:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_recipe_shard_plan_preserves_default_scope_and_limits_exact_recipe():
    base = research_job.default_research_job_plan()
    recipe_id = base.runnable_recipe_ids[0]
    recipe = strategy_recipe(recipe_id)

    shard = research_job.research_job_plan_for_recipe(recipe_id)

    assert shard.requested_families == base.requested_families
    assert shard.runnable_families == (recipe.family,)
    assert shard.runnable_recipe_ids == (recipe_id,)
    assert shard.blocked_families == base.blocked_families
    assert shard.instruments == base.instruments
    assert shard.seed_start == base.seed_start
    assert shard.seed_stop == base.seed_stop
    assert shard.archive_months == base.archive_months


def test_recipe_shard_plan_rejects_recipe_outside_default_public_schedule():
    with pytest.raises(ValueError, match="default autonomous research schedule"):
        research_job.research_job_plan_for_recipe("options-iv-rv-defined-risk")


def test_autonomous_research_matrix_exactly_shards_default_recipe_schedule():
    workflow = _workflow()
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and len(jobs) == 1
    job = next(iter(jobs.values()))

    strategy = job.get("strategy")
    assert isinstance(strategy, dict)
    assert strategy.get("fail-fast") is False
    matrix = strategy.get("matrix")
    assert isinstance(matrix, dict)
    recipe_ids = matrix.get("recipe_id")
    assert isinstance(recipe_ids, list)

    expected = list(research_job.default_research_job_plan().runnable_recipe_ids)
    assert recipe_ids == expected
    assert len(recipe_ids) == 10
    assert len(set(recipe_ids)) == len(recipe_ids)

    env = job.get("env")
    assert isinstance(env, dict)
    assert env.get("MASTERTRD_RESEARCH_RECIPE_ID") == "${{ matrix.recipe_id }}"

    upload_steps = [
        step
        for step in job.get("steps", [])
        if str(step.get("uses", "")).lower().startswith("actions/upload-artifact@")
    ]
    assert len(upload_steps) == 1
    artifact_name = str(upload_steps[0].get("with", {}).get("name", ""))
    assert "${{ github.sha }}" in artifact_name
    assert "${{ matrix.recipe_id }}" in artifact_name


def test_main_uses_requested_recipe_shard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    Path("uv.lock").write_bytes(b"locked")
    monkeypatch.setenv("GITHUB_SHA", "code-v1")
    monkeypatch.setenv("MASTERTRD_RESEARCH_RECIPE_ID", "ema-cross-fast")
    monkeypatch.setenv("MASTERTRD_RESEARCH_ARTIFACT_DIR", str(tmp_path / "out"))

    seen = {}

    def fake_run(plan, **kwargs):
        seen["plan"] = plan
        return {"schema_version": 1, "runs": []}

    monkeypatch.setattr(research_job, "run_research_job", fake_run)

    assert research_job.main() == 0
    plan = seen["plan"]
    assert plan.runnable_recipe_ids == ("ema-cross-fast",)
    assert plan.runnable_families == ("trend",)
