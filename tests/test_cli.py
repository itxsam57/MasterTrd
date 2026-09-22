import json

from mastertrd.cli import main


def test_status_command_prints_safe_snapshot(capsys, monkeypatch):
    monkeypatch.delenv("MASTERTRD_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    assert main(["status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "PAPER"
    assert payload["live_enabled"] is False


def test_strategies_command_prints_catalog(capsys):
    assert main(["strategies"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) >= 189
    assert payload[0]["recipe_id"]


def test_backtest_command_launches_local_job(capsys, monkeypatch, tmp_path):
    from mastertrd.local_jobs import LocalJobReceipt

    receipt = LocalJobReceipt(
        job_id="job-1",
        kind="RESEARCH",
        recipe_id="ema-cross-fast",
        status="RUNNING",
        pid=123,
        created_at="2026-09-12T00:00:00+00:00",
        finished_at=None,
        job_dir=str(tmp_path / "job-1"),
        error=None,
    )
    monkeypatch.setattr("mastertrd.cli.launch_research_job", lambda recipe, root: receipt)
    assert main(["backtest", "--recipe", "ema-cross-fast", "--root", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["job_id"] == "job-1"
    assert payload["status"] == "RUNNING"


def test_jobs_command_lists_local_receipts(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr("mastertrd.cli.list_local_jobs", lambda root: [])
    assert main(["jobs", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_app_command_delegates_to_streamlit(monkeypatch):
    launched = {}

    def fake_run(argv, **kwargs):
        launched["argv"] = argv
        launched["kwargs"] = kwargs
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("mastertrd.cli.subprocess.run", fake_run)
    assert main(["app"]) == 0
    assert launched["argv"][1:4] == ["-m", "streamlit", "run"]
    assert launched["argv"][-2:] == ["--server.address", "127.0.0.1"]


def test_config_command_saves_only_safe_local_settings(capsys, monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(
        "mastertrd.cli.TradingService.save_local_settings",
        lambda self, mode, product: path,
    )
    assert main(["config", "--mode", "TESTNET", "--product", "SPOT"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"config": str(path), "mode": "TESTNET", "product": "SPOT"}
