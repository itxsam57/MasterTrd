from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
