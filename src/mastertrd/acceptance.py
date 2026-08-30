from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    passed: bool
    detail: str


def run_static_acceptance(repo_root: Path) -> tuple[AcceptanceCheck, ...]:
    root = Path(repo_root)
    required = {
        "master_plan": root / "MASTER_PLAN.md",
        "dependency_lock": root / "uv.lock",
    }
    return tuple(
        AcceptanceCheck(name=name, passed=path.is_file(), detail=str(path))
        for name, path in required.items()
    )


def write_acceptance_json(
    output: Path,
    checks: Iterable[AcceptanceCheck],
) -> Path:
    path = Path(output)
    materialized = tuple(checks)
    payload = {
        "passed": all(check.passed for check in materialized),
        "checks": [asdict(check) for check in materialized],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path
