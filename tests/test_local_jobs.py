import json
from pathlib import Path

import pytest

from mastertrd.local_jobs import launch_research_job, list_local_jobs


def test_launch_research_job_uses_separate_process(tmp_path, monkeypatch):
    launched = {}

    class Process:
        pid = 1234

    def fake_popen(argv, **kwargs):
        launched["argv"] = argv
        launched["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("mastertrd.local_jobs._git_head", lambda: "abc123")
    monkeypatch.setattr("mastertrd.local_jobs.subprocess.Popen", fake_popen)
    receipt = launch_research_job("ema-cross-fast", tmp_path)

    assert receipt.pid == 1234
    assert receipt.status == "RUNNING"
    assert "mastertrd.local_job_worker" in launched["argv"]
    assert launched["kwargs"]["start_new_session"] is True
    assert list_local_jobs(tmp_path)[0].recipe_id == "ema-cross-fast"


def test_launch_rejects_non_executable_recipe(tmp_path):
    with pytest.raises(ValueError, match="not executable"):
        launch_research_job("momentum-01", tmp_path)


def test_receipt_is_persisted_as_json(tmp_path, monkeypatch):
    monkeypatch.setattr("mastertrd.local_jobs._git_head", lambda: "abc123")
    monkeypatch.setattr(
        "mastertrd.local_jobs.subprocess.Popen",
        lambda *args, **kwargs: type("P", (), {"pid": 77})(),
    )
    receipt = launch_research_job("ema-cross-fast", tmp_path)
    payload = json.loads((Path(receipt.job_dir) / "receipt.json").read_text())
    assert payload["job_id"] == receipt.job_id
    assert payload["pid"] == 77
    assert payload["recipe_id"] == "ema-cross-fast"


def test_worker_updates_receipt_to_succeeded(tmp_path, monkeypatch):
    monkeypatch.setattr("mastertrd.local_jobs._git_head", lambda: "abc123")
    monkeypatch.setattr(
        "mastertrd.local_jobs.subprocess.Popen",
        lambda *args, **kwargs: type("P", (), {"pid": 88})(),
    )
    receipt = launch_research_job("ema-cross-fast", tmp_path)

    from mastertrd import local_job_worker

    seen = {}

    def fake_main():
        import os
        seen["recipe"] = os.environ["MASTERTRD_RESEARCH_RECIPE_ID"]
        seen["artifact"] = os.environ["MASTERTRD_RESEARCH_ARTIFACT_DIR"]
        seen["code_hash"] = os.environ["MASTERTRD_CODE_HASH"]
        return 0

    monkeypatch.setattr(local_job_worker.research_job, "main", fake_main)
    assert local_job_worker.run_research_worker(
        Path(receipt.job_dir),
        recipe_id="ema-cross-fast",
        code_hash="abc123",
    ) == 0
    final = list_local_jobs(tmp_path)[0]
    assert final.status == "SUCCEEDED"
    assert seen["recipe"] == "ema-cross-fast"
    assert seen["code_hash"] == "abc123"
    assert Path(seen["artifact"]).name == "research"
