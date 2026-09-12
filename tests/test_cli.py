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
