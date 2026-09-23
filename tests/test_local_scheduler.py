from pathlib import Path

from mastertrd.local_scheduler import default_tasks, run_due_tasks


def test_local_scheduler_defines_canary_and_research_tasks():
    tasks = {task.name: task for task in default_tasks()}
    assert set(tasks) == {"public-canary", "autopilot", "autopilot-maintenance"}
    assert tasks["public-canary"].interval_seconds == 6 * 60 * 60
    assert tasks["autopilot"].interval_seconds == 6 * 60 * 60
    assert tasks["autopilot-maintenance"].interval_seconds == 10 * 60


def test_run_due_tasks_launches_only_due_tasks():
    tasks = default_tasks()
    launched = []
    last_run = {
        "public-canary": 100.0,
        "autopilot": 100.0,
        "autopilot-maintenance": 100.0 + 6 * 60 * 60 - 60,
    }
    result = run_due_tasks(
        tasks,
        now=100.0 + 6 * 60 * 60,
        last_run=last_run,
        launch=lambda task: launched.append(task.name),
    )
    assert launched == ["public-canary", "autopilot"]
    assert result["public-canary"] == 100.0 + 6 * 60 * 60
    assert result["autopilot"] == 100.0 + 6 * 60 * 60
    assert result["autopilot-maintenance"] == 100.0 + 6 * 60 * 60 - 60


def test_consumer_runtime_has_no_required_hosted_cron():
    for name in ("autonomous-research.yml", "public-binance-canary.yml"):
        text = Path(".github/workflows", name).read_text(encoding="utf-8")
        assert "  schedule:" not in text
