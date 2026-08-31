from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "autonomous-research.yml"


def test_autonomous_research_workflow_delegates_to_checked_in_job():
    text = WORKFLOW.read_text(encoding="utf-8")
    lower = text.lower()

    assert "python -m mastertrd.research_job" in lower
    assert "python - <<'py'" not in lower
    assert "generate_candidate(" not in lower
    assert "family='trend'" not in lower
    assert "seed=42" not in lower


def test_default_research_job_plan_is_broad_and_blocks_missing_specialist_data():
    spec = importlib.util.find_spec("mastertrd.research_job")
    assert spec is not None, "checked-in mastertrd.research_job entrypoint is required"
    research_job = importlib.import_module("mastertrd.research_job")

    plan = research_job.default_research_job_plan()

    assert len(plan.requested_families) > 1
    assert len(plan.instruments) > 1
    assert plan.seed_stop - plan.seed_start > 1
    assert "trend" in plan.runnable_families
    assert "momentum" in plan.runnable_families

    blocked = {item.family: item.reason for item in plan.blocked_families}
    assert blocked["options"] == "qualifying_public_option_data_unavailable"
    assert blocked["scalping"] == "qualifying_public_tick_data_unavailable"
    assert blocked["market_making"] == "qualifying_public_l2_data_unavailable"
