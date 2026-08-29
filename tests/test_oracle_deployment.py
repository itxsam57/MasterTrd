from pathlib import Path

from mastertrd.oracle import OracleDeploymentSpec, render_bootstrap_script, render_env_template, render_systemd_unit


ROOT = Path(__file__).resolve().parents[1]
ORACLE_DIR = ROOT / "deploy" / "oracle"


def spec() -> OracleDeploymentSpec:
    return OracleDeploymentSpec(
        app_dir="/opt/mastertrd",
        service_user="mastertrd",
        python_bin="/opt/mastertrd/.venv/bin/python",
        module="mastertrd.live_node",
        env_file="/etc/mastertrd/mastertrd.env",
    )


def test_oracle_adapter_is_dormant_and_never_embeds_secrets():
    text = render_env_template()
    assert "ORACLE_ENABLED=false" in text
    assert "LIVE_TRADING_ENABLED=false" in text
    assert "MASTERTRD_MODE=PAPER" in text
    for namespace in ("DEMO", "TESTNET", "LIVE"):
        assert f"BINANCE_{namespace}_API_KEY=" in text
        assert f"BINANCE_{namespace}_API_SECRET=" in text
        assert f"BINANCE_{namespace}_ACCOUNT_ID=" in text
    assert "BINANCE_API_KEY=" not in text
    assert "BINANCE_API_SECRET=" not in text
    assert "changeme" not in text.lower()


def test_systemd_unit_restarts_and_loads_protected_environment():
    unit = render_systemd_unit(spec())
    assert "User=mastertrd" in unit
    assert "EnvironmentFile=/etc/mastertrd/mastertrd.env" in unit
    assert "Restart=on-failure" in unit
    assert "RestartSec=5" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/opt/mastertrd" in unit
    assert "mastertrd.live_node" in unit


def test_bootstrap_targets_arm64_or_amd64_linux_and_installs_health_recovery_hooks():
    script = render_bootstrap_script(spec())
    assert "uname -s" in script
    assert "aarch64|arm64|x86_64|amd64" in script
    assert "systemctl enable mastertrd.service" in script
    assert "logrotate" in script
    assert "mastertrd-health" in script
    assert "chmod 600 /etc/mastertrd/mastertrd.env" in script
    assert "ORACLE_ENABLED=false" in script


def test_portable_oracle_deployment_artifacts_are_committed():
    required = (
        "bootstrap.sh",
        "mastertrd.service",
        "mastertrd-health",
        "mastertrd.logrotate",
        "mastertrd.env.example",
    )
    for name in required:
        path = ORACLE_DIR / name
        assert path.is_file(), f"missing Oracle deployment artifact: {path.relative_to(ROOT)}"
    assert (ROOT / ".github" / "workflows" / "oracle-deploy.yml").is_file()


def test_committed_oracle_environment_and_service_fail_closed():
    env = (ORACLE_DIR / "mastertrd.env.example").read_text(encoding="utf-8")
    assert "MASTERTRD_MODE=PAPER" in env
    assert "LIVE_TRADING_ENABLED=false" in env
    assert "ORACLE_ENABLED=false" in env
    assert "BINANCE_PRODUCT=SPOT" in env
    assert "changeme" not in env.lower()

    unit = (ORACLE_DIR / "mastertrd.service").read_text(encoding="utf-8")
    assert "User=mastertrd" in unit
    assert "EnvironmentFile=/etc/mastertrd/mastertrd.env" in unit
    assert "ExecStart=/opt/mastertrd/.venv/bin/python -m mastertrd.live_node" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "/var/lib/mastertrd" in unit
    assert "/var/log/mastertrd" in unit


def test_committed_bootstrap_pins_exact_git_sha_and_never_starts_live_automatically():
    script = (ORACLE_DIR / "bootstrap.sh").read_text(encoding="utf-8")
    assert "uname -s" in script
    assert "aarch64|arm64|x86_64|amd64" in script
    assert "MASTERTRD_REF" in script
    assert "{40}" in script
    assert "checkout --detach" in script
    assert "uv sync --locked" in script
    assert "systemctl enable mastertrd.service" in script
    assert "systemctl start mastertrd.service" not in script
    assert "LIVE_TRADING_ENABLED=true" not in script


def test_oracle_health_logrotate_and_manual_deploy_workflow_are_safe():
    health = (ORACLE_DIR / "mastertrd-health").read_text(encoding="utf-8")
    assert "systemctl is-active --quiet mastertrd.service" in health
    assert "NRestarts" in health

    logrotate = (ORACLE_DIR / "mastertrd.logrotate").read_text(encoding="utf-8")
    assert "/var/log/mastertrd/*.log" in logrotate
    assert "rotate 14" in logrotate
    assert "compress" in logrotate

    workflow = (ROOT / ".github" / "workflows" / "oracle-deploy.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "pull_request:" not in workflow
    assert "secrets.ORACLE_HOST" in workflow
    assert "secrets.ORACLE_USER" in workflow
    assert "secrets.ORACLE_SSH_KEY" in workflow
    assert "LIVE_TRADING_ENABLED=true" not in workflow
