from pathlib import Path

import yaml

from mastertrd.oracle import (
    OracleDeploymentSpec,
    render_bootstrap_script,
    render_env_template,
    render_oracle_bundle,
    render_systemd_unit,
)


ROOT = Path(__file__).resolve().parents[1]


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


def test_oracle_env_template_matches_repository_owned_paper_runtime_contract():
    text = render_env_template()
    for name in (
        "MASTERTRD_CANDIDATE_MANIFEST",
        "MASTERTRD_SESSION_STATE",
        "MASTERTRD_CODE_HASH",
    ):
        assert f"{name}=" in text
    assert "MASTERTRD_EXECUTION_FACTORY" not in text


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


def test_systemd_and_bootstrap_allow_documented_paper_state_directory():
    unit = render_systemd_unit(spec())
    script = render_bootstrap_script(spec())
    assert "/var/lib/mastertrd" in unit
    assert "mkdir -p" in script and "/var/lib/mastertrd" in script
    assert "chown -R mastertrd:mastertrd" in script and "/var/lib/mastertrd" in script


def test_bootstrap_targets_arm64_or_amd64_linux_and_installs_health_recovery_hooks():
    script = render_bootstrap_script(spec())
    assert "uname -s" in script
    assert "aarch64|arm64|x86_64|amd64" in script
    assert "systemctl enable mastertrd.service" in script
    assert "logrotate" in script
    assert "mastertrd-health" in script
    assert "chmod 600 /etc/mastertrd/mastertrd.env" in script
    assert "ORACLE_ENABLED=false" in script


def test_render_oracle_bundle_exposes_every_operator_artifact_without_credentials():
    bundle = render_oracle_bundle(spec())
    assert bundle.env_file == "/etc/mastertrd/mastertrd.env"
    assert "EnvironmentFile=/etc/mastertrd/mastertrd.env" in bundle.systemd_unit
    assert "ExecStart=/opt/mastertrd/.venv/bin/python -m mastertrd.live_node" in bundle.systemd_unit
    assert "Restart=on-failure" in bundle.systemd_unit
    assert bundle.health_command == "/usr/local/bin/mastertrd-health"
    assert "/var/log/mastertrd/*.log" in bundle.logrotate_config
    assert "rotate 14" in bundle.logrotate_config
    assert "ORACLE_ENABLED=false" in bundle.env_template
    assert "LIVE_TRADING_ENABLED=false" in bundle.env_template
    assert "changeme" not in repr(bundle).lower()


def test_oracle_deploy_workflow_is_manual_environment_gated_and_fail_closed():
    path = ROOT / ".github" / "workflows" / "oracle-deploy.yml"
    assert path.exists(), "missing Oracle deployment workflow"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on", workflow.get(True, {}))
    assert set(triggers) == {"workflow_dispatch"}
    assert workflow.get("permissions") == {"contents": "read"}
    jobs = workflow["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert job.get("environment") == "oracle"

    upper = text.upper()
    assert "ORACLE_ENABLED" in upper
    assert '!= "TRUE"' in upper or "!= 'TRUE'" in upper
    assert "EXIT 1" in upper
    assert "ORACLE_HOST" in upper
    assert "ORACLE_SSH_KEY" in upper
    assert "ORACLE_KNOWN_HOSTS" in upper
    assert "UV LOCK --CHECK" in upper
    assert "UV SYNC --LOCKED" in upper or "UV SYNC --FROZEN" in upper
    assert "MASTERTRD.LIVE_NODE" in upper
    assert "BINANCE_LIVE_API_KEY" not in upper
    assert "BINANCE_LIVE_API_SECRET" not in upper


def test_oracle_deploy_checks_current_paper_inputs_not_deleted_factory_knob():
    text = (ROOT / ".github" / "workflows" / "oracle-deploy.yml").read_text(encoding="utf-8")
    upper = text.upper()
    assert "MASTERTRD_EXECUTION_FACTORY" not in upper
    for name in (
        "MASTERTRD_CANDIDATE_MANIFEST",
        "MASTERTRD_SESSION_STATE",
        "MASTERTRD_CODE_HASH",
    ):
        assert name in upper
