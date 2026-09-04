from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import mastertrd.research_job as research_job
from mastertrd.strategy_universe import strategy_recipe


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "autonomous-research.yml"
RESEARCH_STACK = WORKFLOWS / "research-stack.yml"


def _workflow() -> dict:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _on(workflow: dict) -> dict:
    value = workflow.get("on", workflow.get(True, {}))
    assert isinstance(value, dict)
    return value


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
    assert shard.archive_months >= base.archive_months


def test_recipe_shard_plan_rejects_recipe_outside_public_bar_schedule_with_blocker():
    with pytest.raises(ValueError, match="not runnable in public BAR research") as exc_info:
        research_job.research_job_plan_for_recipe("options-iv-rv-defined-risk")
    assert "blocked:" in str(exc_info.value)


def test_autonomous_research_matrix_exactly_shards_complete_public_recipe_schedule():
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
    assert recipe_ids == list(research_job.scheduled_public_recipe_ids())
    assert len(recipe_ids) >= 25
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


def test_research_stack_owns_sharding_contract():
    text = RESEARCH_STACK.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert isinstance(workflow, dict)
    triggers = _on(workflow)
    required = "tests/test_research_sharding.py"
    assert required in set(triggers["push"]["paths"])
    assert required in set(triggers["pull_request"]["paths"])
    assert required in text


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


def test_swing_recipe_shards_have_enough_archive_months_for_daily_holdout():
    shard = research_job.research_job_plan_for_recipe("pullback-crypto")

    # Daily candidates need at least 250 observations for the configured
    # 4x50 research windows plus a 50-bar hidden holdout. Nine calendar
    # months is the conservative minimum; eight can be shorter than 250 days.
    assert shard.archive_months >= 9
