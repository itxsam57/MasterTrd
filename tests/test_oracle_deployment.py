from mastertrd.oracle import OracleDeploymentSpec, render_env_template, render_systemd_unit, render_bootstrap_script


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
