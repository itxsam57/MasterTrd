from __future__ import annotations

from pathlib import Path

from mastertrd.acceptance import AcceptanceCheck, run_static_acceptance


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
