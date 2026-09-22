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
    monkeypatch.setenv("MASTERTRD_RESEARCH_RECIPE_ID", "prior-recipe")
    monkeypatch.delenv("MASTERTRD_RESEARCH_ARTIFACT_DIR", raising=False)
    monkeypatch.setenv("MASTERTRD_CODE_HASH", "prior-hash")
    assert local_job_worker.run_research_worker(
        Path(receipt.job_dir),
        recipe_id="ema-cross-fast",
        code_hash="abc123",
    ) == 0
    assert __import__("os").environ["MASTERTRD_RESEARCH_RECIPE_ID"] == "prior-recipe"
    assert "MASTERTRD_RESEARCH_ARTIFACT_DIR" not in __import__("os").environ
    assert __import__("os").environ["MASTERTRD_CODE_HASH"] == "prior-hash"
    final = list_local_jobs(tmp_path)[0]
    assert final.status == "SUCCEEDED"
    assert seen["recipe"] == "ema-cross-fast"
    assert seen["code_hash"] == "abc123"
    assert Path(seen["artifact"]).name == "research"


def test_launch_research_matrix_expands_only_compatible_cells(tmp_path, monkeypatch):
    from mastertrd.local_jobs import LocalJobReceipt, launch_research_matrix

    launched = []

    def fake_launch(recipe_id, root, **kwargs):
        launched.append((recipe_id, kwargs))
        return LocalJobReceipt(
            job_id=f"job-{len(launched)}",
            kind="RESEARCH",
            recipe_id=recipe_id,
            status="RUNNING",
            pid=len(launched),
            created_at="2026-09-22T00:00:00+00:00",
            finished_at=None,
            job_dir=str(tmp_path / f"job-{len(launched)}"),
            error=None,
            **kwargs,
        )

    monkeypatch.setattr("mastertrd.local_jobs.launch_research_job", fake_launch)
    receipts = launch_research_matrix(
        ("ema-cross-fast", "rsi-momentum-fast"),
        tmp_path,
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        timeframes=("5m", "15m", "4h"),
        seed_start=10,
        seed_stop=12,
        archive_months=3,
    )

    assert receipts
    assert all(item[1]["instruments"] == ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE") for item in launched)
    assert all(item[1]["seed_start"] == 10 and item[1]["seed_stop"] == 12 for item in launched)
    assert all(item[1]["archive_months"] == 3 for item in launched)
    assert ("ema-cross-fast", "4h") in {(recipe, kwargs["timeframe"]) for recipe, kwargs in launched}
    assert ("rsi-momentum-fast", "5m") in {(recipe, kwargs["timeframe"]) for recipe, kwargs in launched}


def test_worker_applies_and_restores_matrix_environment(tmp_path, monkeypatch):
    from mastertrd import local_job_worker

    monkeypatch.setattr("mastertrd.local_jobs._git_head", lambda: "abc123")
    monkeypatch.setattr(
        "mastertrd.local_jobs.subprocess.Popen",
        lambda *args, **kwargs: type("P", (), {"pid": 99})(),
    )
    receipt = launch_research_job(
        "ema-cross-fast",
        tmp_path,
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        timeframe="4h",
        seed_start=3,
        seed_stop=5,
        archive_months=4,
    )
    seen = {}

    def fake_main():
        import os
        for key in (
            "MASTERTRD_RESEARCH_INSTRUMENTS",
            "MASTERTRD_RESEARCH_TIMEFRAMES",
            "MASTERTRD_RESEARCH_SEED_START",
            "MASTERTRD_RESEARCH_SEED_STOP",
            "MASTERTRD_RESEARCH_ARCHIVE_MONTHS",
        ):
            seen[key] = os.environ[key]
        return 0

    monkeypatch.setattr(local_job_worker.research_job, "main", fake_main)
    monkeypatch.setenv("MASTERTRD_RESEARCH_TIMEFRAMES", "prior")
    assert local_job_worker.run_research_worker(
        Path(receipt.job_dir),
        recipe_id="ema-cross-fast",
        code_hash="abc123",
        instruments="BTCUSDT.BINANCE,ETHUSDT.BINANCE",
        timeframe="4h",
        seed_start=3,
        seed_stop=5,
        archive_months=4,
    ) == 0

    assert seen["MASTERTRD_RESEARCH_INSTRUMENTS"] == "BTCUSDT.BINANCE,ETHUSDT.BINANCE"
    assert seen["MASTERTRD_RESEARCH_TIMEFRAMES"] == "4h"
    assert seen["MASTERTRD_RESEARCH_SEED_START"] == "3"
    assert seen["MASTERTRD_RESEARCH_SEED_STOP"] == "5"
    assert seen["MASTERTRD_RESEARCH_ARCHIVE_MONTHS"] == "4"
    assert __import__("os").environ["MASTERTRD_RESEARCH_TIMEFRAMES"] == "prior"


def test_local_result_rows_preserves_losses_failures_and_report_path(tmp_path):
    from mastertrd.local_jobs import LocalJobReceipt, local_result_rows, save_receipt

    job_dir = tmp_path / "job-1"
    receipt = LocalJobReceipt(
        job_id="job-1",
        kind="RESEARCH",
        recipe_id="ema-cross-fast",
        status="SUCCEEDED",
        pid=1,
        created_at="2026-09-22T00:00:00+00:00",
        finished_at="2026-09-22T00:01:00+00:00",
        job_dir=str(job_dir),
        error=None,
        timeframe="4h",
    )
    save_receipt(receipt)
    report = job_dir / "research" / "research-report.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "paper_queued": 0,
                        "finalists": [
                            {"state": "REJECTED", "score": -0.12},
                            {"state": "QUARANTINED", "score": -0.05},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    row = local_result_rows(tmp_path)[0]
    assert row["best_score"] == -0.05
    assert row["best_state"] == "QUARANTINED"
    assert row["paper_queued"] == 0
    assert row["report"] == str(report)


def test_local_paper_candidates_discovers_only_paper_handoffs(tmp_path):
    from mastertrd.local_jobs import LocalJobReceipt, local_paper_candidates, save_receipt

    job_dir = tmp_path / "job-paper"
    receipt = LocalJobReceipt(
        job_id="job-paper",
        kind="RESEARCH",
        recipe_id="ema-cross-fast",
        status="SUCCEEDED",
        pid=1,
        created_at="2026-09-22T00:00:00+00:00",
        finished_at="2026-09-22T00:01:00+00:00",
        job_dir=str(job_dir),
        error=None,
        timeframe="1m",
    )
    save_receipt(receipt)
    report_path = job_dir / "research" / "research-report.json"
    report_path.parent.mkdir(parents=True)
    manifest = {
        "candidate": {"strategy_id": "paper-a"},
        "strategy_id": "paper-a",
        "genome_hash": "g-a",
        "state": "PAPER",
        "code_hash": "c",
        "dataset_hash": "d",
        "lock_hash": "l",
        "recipe_id": "ema-cross-fast",
    }
    report_path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "recipe_id": "ema-cross-fast",
                        "timeframe": "1m",
                        "paper_candidates": [manifest],
                    },
                    {
                        "recipe_id": "ema-cross-fast",
                        "timeframe": "5m",
                        "paper_candidates": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = local_paper_candidates(tmp_path)
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "paper-a"
    assert rows[0]["manifest"] == manifest
