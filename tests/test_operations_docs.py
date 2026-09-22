from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text() -> str:
    return (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")


def test_operations_runbook_is_local_first_and_covers_runtime_safety():
    text = _text()
    upper = text.upper()
    lower = text.lower()

    for mode in ("PAPER", "DEMO", "TESTNET", "LIVE"):
        assert mode in upper
    for topic in ("WINDOWS", "LINUX", "RECOVERY", "LOG", "EMERGENCY KILL", "ROLLBACK", "SECRET ROTATION"):
        assert topic in upper

    assert "mastertrd app" in text
    assert "mastertrd scheduler" in text
    assert "mastertrd trading" in text
    assert "python -m mastertrd.live_node" not in text
    assert "LIVE_TRADING_ENABLED=false" in text
    assert "LIVE_TRADING_ENABLED=true" in text
    assert "provider admission" in lower


def test_operations_runbook_lists_exchange_inputs_without_values():
    text = _text()
    for name in (
        "BINANCE_TESTNET_API_KEY",
        "BINANCE_TESTNET_API_SECRET",
        "BINANCE_TESTNET_ACCOUNT_ID",
        "BINANCE_LIVE_API_KEY",
        "BINANCE_LIVE_API_SECRET",
        "BINANCE_LIVE_ACCOUNT_ID",
    ):
        assert name in text
    assert "changeme" not in text.lower()


def test_operations_runbook_has_no_required_cloud_runtime():
    text = _text()
    assert "ORACLE_ENABLED" not in text
    assert "oracle-deploy.yml" not in text
    assert "Oracle Deploy" not in text
    assert "Vercel" in text
    assert "PostHog" in text
    assert "Neon" in text
    assert "optional" in text.lower() or "not required" in text.lower()
