from __future__ import annotations

import json
from pathlib import Path

from mastertrd.acceptance import (
    AcceptanceCheck,
    run_static_acceptance,
    write_acceptance_json,
)


def test_acceptance_check_is_immutable() -> None:
    check = AcceptanceCheck(name="master_plan", passed=True, detail="ok")
    assert check.name == "master_plan"
    assert check.passed is True
    assert check.detail == "ok"


def test_static_acceptance_requires_lock_and_master_plan(tmp_path: Path) -> None:
    checks = run_static_acceptance(tmp_path)
    by_name = {check.name: check for check in checks}

    assert by_name["master_plan"].passed is False
    assert by_name["dependency_lock"].passed is False


def test_static_acceptance_passes_when_required_files_exist(tmp_path: Path) -> None:
    (tmp_path / "MASTER_PLAN.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    checks = run_static_acceptance(tmp_path)
    by_name = {check.name: check for check in checks}

    assert by_name["master_plan"].passed is True
    assert by_name["dependency_lock"].passed is True


def test_write_acceptance_json_is_machine_readable(tmp_path: Path) -> None:
    output = tmp_path / "acceptance.json"
    checks = (
        AcceptanceCheck("master_plan", True, "MASTER_PLAN.md"),
        AcceptanceCheck("dependency_lock", False, "uv.lock"),
    )

    written = write_acceptance_json(output, checks)

    assert written == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "passed": False,
        "checks": [
            {"name": "master_plan", "passed": True, "detail": "MASTER_PLAN.md"},
            {"name": "dependency_lock", "passed": False, "detail": "uv.lock"},
        ],
    }
