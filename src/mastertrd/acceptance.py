from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import json
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MasterTrd completion acceptance checks")
    parser.add_argument("repo_root", nargs="?", default=".")
    parser.add_argument("--write", default="artifacts/acceptance.json")
    args = parser.parse_args(argv)

    checks = run_static_acceptance(Path(args.repo_root))
    write_acceptance_json(Path(args.write), checks)
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
