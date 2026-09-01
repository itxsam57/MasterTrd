from pathlib import Path

from mastertrd.oracle import OracleDeploymentSpec, render_bootstrap_script, render_env_template, render_systemd_unit


ROOT = Path(__file__).resolve().parents[1]


def _spec() -> OracleDeploymentSpec:
    return OracleDeploymentSpec(
        app_dir="/opt/mastertrd",
        service_user="mastertrd",
        python_bin="/opt/mastertrd/.venv/bin/python",
        module="mastertrd.live_node",
        env_file="/etc/mastertrd/mastertrd.env",
    )


def test_oracle_env_exposes_durable_paper_evidence_and_rotation_paths():
    text = render_env_template()
    for name in (
        "MASTERTRD_PAPER_ARCHIVE",
        "MASTERTRD_PAPER_HISTORY_DIR",
        "MASTERTRD_PAPER_ROTATION_REQUEST",
        "MASTERTRD_PAPER_ROTATE_AFTER_SECONDS",
    ):
        assert f"{name}=" in text
    assert "MASTERTRD_PAPER_ROTATE_AFTER_SECONDS=86400" in text


def test_oracle_rotation_is_requested_by_guarded_timer_without_weakening_service_restart_policy():
    unit = render_systemd_unit(_spec())
    bootstrap = render_bootstrap_script(_spec())

    assert "Restart=on-failure" in unit
    assert "Restart=always" not in unit
    assert "mastertrd-paper-rotate-request" in bootstrap
    assert "mastertrd-paper-rotate.service" in bootstrap
    assert "mastertrd-paper-rotate.timer" in bootstrap
    assert "OnUnitActiveSec=1m" in bootstrap
    assert "MASTERTRD_MODE" in bootstrap
    assert "LIVE_TRADING_ENABLED" in bootstrap
    assert "MASTERTRD_PAPER_ROTATE_AFTER_SECONDS" in bootstrap
    assert "MASTERTRD_PAPER_ROTATION_REQUEST" in bootstrap
    assert "JsonPaperSessionStore" in bootstrap
    assert "systemctl restart mastertrd.service" not in bootstrap


def test_oracle_deploy_uses_candidate_and_code_identity_scoped_paper_state():
    text = (ROOT / ".github" / "workflows" / "oracle-deploy.yml").read_text(encoding="utf-8")

    assert "PAPER_GENOME_HASH" in text
    assert "GITHUB_ENV" in text
    assert "MASTERTRD_PAPER_ARCHIVE" in text
    assert "MASTERTRD_PAPER_HISTORY_DIR" in text
    assert "MASTERTRD_PAPER_ROTATION_REQUEST" in text
    assert "MASTERTRD_PAPER_ROTATE_AFTER_SECONDS" in text
    assert "$GITHUB_SHA" in text
    assert "$PAPER_GENOME_HASH" in text
    assert "/var/lib/mastertrd/paper/" in text
    assert "LIVE_TRADING_ENABLED=false" in text
