from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence

from .source_identity import git_head as _source_git_head


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    name: str
    interval_seconds: float
    module: str


def default_tasks() -> tuple[ScheduledTask, ...]:
    return (
        ScheduledTask("public-canary", 6 * 60 * 60, "mastertrd.public_market_canary"),
        ScheduledTask("autopilot", 6 * 60 * 60, "mastertrd.autopilot"),
    )


def run_due_tasks(
    tasks: Sequence[ScheduledTask],
    *,
    now: float,
    last_run: Mapping[str, float],
    launch: Callable[[ScheduledTask], object],
) -> dict[str, float]:
    updated = dict(last_run)
    for task in tasks:
        previous = float(updated.get(task.name, now - task.interval_seconds))
        if now - previous >= task.interval_seconds:
            launch(task)
            updated[task.name] = now
    return updated


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_head() -> str:
    return _source_git_head()


def _launch_task(task: ScheduledTask, artifact_root: Path) -> subprocess.Popen[bytes]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_root = artifact_root / task.name
    task_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MASTERTRD_MODE"] = "PAPER"
    env["LIVE_TRADING_ENABLED"] = "false"
    env["MASTERTRD_CODE_HASH"] = _git_head()
    if task.name == "public-canary":
        env["MASTERTRD_CANARY_RECEIPT"] = str(task_root / f"{stamp}.json")
    elif task.name == "autopilot":
        env["MASTERTRD_AUTOPILOT_ARTIFACT_DIR"] = str(task_root / stamp)

    log = (task_root / f"{stamp}.log").open("ab")
    return subprocess.Popen(
        [sys.executable, "-m", task.module],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _load_state(path: Path, tasks: Sequence[ScheduledTask], now: float) -> dict[str, float]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): float(value) for key, value in payload.items()}
    return {task.name: now - task.interval_seconds for task in tasks}


def _save_state(path: Path, state: Mapping[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(state), sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_scheduler(*, poll_seconds: float = 60.0, artifact_root: Path = Path("artifacts/scheduler")) -> None:
    tasks = default_tasks()
    state_path = artifact_root / "state.json"
    now = time.time()
    state = _load_state(state_path, tasks, now)
    while True:
        now = time.time()
        state = run_due_tasks(
            tasks,
            now=now,
            last_run=state,
            launch=lambda task: _launch_task(task, artifact_root),
        )
        _save_state(state_path, state)
        time.sleep(poll_seconds)
