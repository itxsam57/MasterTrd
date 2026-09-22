from pathlib import Path


def test_runtime_has_no_oracle_product_path():
    for path in (
        "src/mastertrd/oracle.py",
        "src/mastertrd/oracle_paper_status.py",
        "src/mastertrd/paper_diagnostics.py",
        ".github/workflows/oracle-deploy.yml",
        ".github/workflows/paper-status.yml",
        "src/mastertrd/live_node.py",
    ):
        assert not Path(path).exists()
    assert Path("src/mastertrd/asset_transfer.py").exists()


def test_runtime_config_has_no_oracle_flag():
    from mastertrd.runtime import RuntimeConfig

    assert "oracle_enabled" not in RuntimeConfig.__dataclass_fields__


def test_active_product_docs_are_local_first_and_keep_live_safety():
    paths = (Path("README.md"), Path("MASTER_PLAN.md"), Path("docs/OPERATIONS.md"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    lower = text.lower()

    for forbidden in ("ORACLE_ENABLED", "oracle-deploy.yml", "Oracle Deploy"):
        assert forbidden not in text

    for required in (
        "mastertrd app",
        "PAPER",
        "LIVE",
        "LIVE_TRADING_ENABLED=false",
        "LIVE_TRADING_ENABLED=true",
        "mastertrd trading",
    ):
        assert required in text

    for required_topic in ("recovery", "emergency kill", "credentials", "logs"):
        assert required_topic in lower


def test_runtime_artifacts_and_private_state_are_git_ignored():
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    for required in ("artifacts/", "*.duckdb", "*.parquet", ".env"):
        assert required in ignored
