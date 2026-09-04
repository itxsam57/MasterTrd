from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operations_runbook_covers_every_runtime_and_emergency_path():
    path = ROOT / "docs" / "OPERATIONS.md"
    assert path.exists(), "missing operations runbook"
    text = path.read_text(encoding="utf-8")
    upper = text.upper()

    for mode in ("PAPER", "DEMO", "TESTNET", "LIVE"):
        assert mode in upper
    for topic in (
        "WINDOWS",
        "LINUX",
        "RECOVERY",
        "LOG",
        "EMERGENCY KILL",
        "ROLLBACK",
        "SECRET ROTATION",
        "OWNER INPUT",
    ):
        assert topic in upper

    assert "mastertrd.live_node" in text
    assert "/etc/mastertrd/mastertrd.env" in text
    assert "ORACLE_ENABLED=true" in text
    assert "LIVE_TRADING_ENABLED=true" in text
    assert "LIVE_TRADING_ENABLED=false" in text
    assert "mastertrd-health" in text


def test_operations_runbook_describes_identity_bound_oracle_paper_handoff():
    text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    for value in (
        "paper_candidates_json",
        "/var/lib/mastertrd/paper/<sha>/<genome_hash>/",
        "/etc/mastertrd/paper/<instance>.env",
        "MASTERTRD_PAPER_ROTATE_AFTER_SECONDS=600",
        "MASTERTRD_CODE_HASH",
        "Autonomous Research",
        "GITHUB_SHA",
    ):
        assert value in text
    assert "MASTERTRD_EXECUTION_FACTORY" not in text
    assert "do not reuse an older research artifact" in text.lower()


def test_operations_runbook_keeps_oracle_live_activation_owner_controlled():
    text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "oracle deploy is not the live deployment/start mechanism" in lower
    assert "refuses automated host mutation or restart" in lower
    assert "LIVE_TRADING_ENABLED=false" in text
    assert "LIVE_TRADING_ENABLED=true" in text


def test_operations_runbook_keeps_vercel_out_of_persistent_execution():
    text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8").lower()
    assert "vercel" in text
    assert "persistent" in text
    assert "low-latency" in text or "low latency" in text
    assert "read-only" in text or "read only" in text
    assert "dashboard" in text or "api" in text


def test_operations_runbook_lists_exact_owner_inputs_without_embedding_values():
    text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    for name in (
        "ORACLE_ENABLED",
        "ORACLE_HOST",
        "ORACLE_SSH_USER",
        "ORACLE_SSH_KEY",
        "ORACLE_KNOWN_HOSTS",
    ):
        assert name in text
    assert "BINANCE_TESTNET_API_KEY" in text
    assert "BINANCE_TESTNET_API_SECRET" in text
    assert "BINANCE_TESTNET_ACCOUNT_ID" in text
    assert "BINANCE_LIVE_API_KEY" in text
    assert "BINANCE_LIVE_API_SECRET" in text
    assert "BINANCE_LIVE_ACCOUNT_ID" in text
    assert "changeme" not in text.lower()
