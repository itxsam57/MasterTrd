from pathlib import Path

import pytest
import yaml

import mastertrd.oracle as oracle_module
from mastertrd.genome import StrategyGenome
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


def paper_candidate_manifest(*, code_hash: str = "code-v1", lock_hash: str = "lock-v1") -> dict[str, object]:
    candidate = StrategyGenome(
        strategy_id="R-oracle-paper",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="5m",
        entry={"kind": "ema_cross", "fast_period": 8, "slow_period": 21, "trade_size": "0.01"},
        exit={"kind": "cross_reverse"},
    )
    return {
        "candidate": candidate.canonical_payload(),
        "strategy_id": candidate.strategy_id,
        "genome_hash": candidate.genome_hash,
        "code_hash": code_hash,
        "dataset_hash": "dataset-v1",
        "lock_hash": lock_hash,
        "recipe_id": "ema-cross-balanced",
    }


def test_oracle_deployment_spec_rejects_blank_required_fields():
    values = {
        "app_dir": "/opt/mastertrd",
        "service_user": "mastertrd",
        "python_bin": "/opt/mastertrd/.venv/bin/python",
        "module": "mastertrd.live_node",
        "env_file": "/etc/mastertrd/mastertrd.env",
    }
    for field in tuple(values):
        invalid = dict(values)
        invalid[field] = " "
        with pytest.raises(ValueError, match=field):
            OracleDeploymentSpec(**invalid)


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


def test_oracle_paper_candidate_manifest_is_identity_bound_to_exact_source():
    validator = oracle_module.validate_paper_candidate_manifest
    manifest = paper_candidate_manifest()

    candidate = validator(
        manifest,
        expected_code_hash="code-v1",
        expected_lock_hash="lock-v1",
    )
    assert candidate.strategy_id == "R-oracle-paper"
    assert candidate.genome_hash == manifest["genome_hash"]

    with pytest.raises(ValueError, match="code_hash"):
        validator(manifest, expected_code_hash="wrong-code", expected_lock_hash="lock-v1")
    with pytest.raises(ValueError, match="lock_hash"):
        validator(manifest, expected_code_hash="code-v1", expected_lock_hash="wrong-lock")

    wrong_identity = dict(manifest)
    wrong_identity["genome_hash"] = "0" * 64
    with pytest.raises(ValueError, match="genome_hash"):
        validator(wrong_identity, expected_code_hash="code-v1", expected_lock_hash="lock-v1")

    wrong_strategy = dict(manifest)
    wrong_strategy["strategy_id"] = "R-wrong"
    with pytest.raises(ValueError, match="strategy_id"):
        validator(wrong_strategy, expected_code_hash="code-v1", expected_lock_hash="lock-v1")


def test_oracle_paper_candidate_manifest_rejects_missing_or_invalid_provenance():
    validator = oracle_module.validate_paper_candidate_manifest
    manifest = paper_candidate_manifest()

    with pytest.raises(ValueError, match="expected_code_hash"):
        validator(manifest, expected_code_hash="", expected_lock_hash="lock-v1")
    with pytest.raises(ValueError, match="expected_lock_hash"):
        validator(manifest, expected_code_hash="code-v1", expected_lock_hash="")

    missing_candidate = dict(manifest)
    missing_candidate.pop("candidate")
    with pytest.raises(ValueError, match="candidate is required"):
        validator(missing_candidate, expected_code_hash="code-v1", expected_lock_hash="lock-v1")

    invalid_candidate = dict(manifest)
    invalid_candidate["candidate"] = {"strategy_id": "incomplete"}
    with pytest.raises(ValueError, match="candidate is invalid"):
        validator(invalid_candidate, expected_code_hash="code-v1", expected_lock_hash="lock-v1")

    for field in ("strategy_id", "genome_hash", "code_hash", "dataset_hash", "lock_hash"):
        missing = dict(manifest)
        missing[field] = " "
        with pytest.raises(ValueError, match=field):
            validator(missing, expected_code_hash="code-v1", expected_lock_hash="lock-v1")


def test_oracle_paper_candidate_manifest_rejects_unsupported_runtime_universe():
    validator = oracle_module.validate_paper_candidate_manifest
    manifest = paper_candidate_manifest()

    raw_candidate = dict(manifest["candidate"])
    raw_candidate["instruments"] = ["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"]
    candidate = StrategyGenome(**raw_candidate)
    multi = dict(manifest)
    multi["candidate"] = candidate.canonical_payload()
    multi["genome_hash"] = candidate.genome_hash
    with pytest.raises(ValueError, match="one instrument"):
        validator(multi, expected_code_hash="code-v1", expected_lock_hash="lock-v1")

    raw_candidate = dict(manifest["candidate"])
    raw_candidate["instruments"] = ["BTC-USD.KRAKEN"]
    candidate = StrategyGenome(**raw_candidate)
    wrong_venue = dict(manifest)
    wrong_venue["candidate"] = candidate.canonical_payload()
    wrong_venue["genome_hash"] = candidate.genome_hash
    with pytest.raises(ValueError, match="BINANCE instrument"):
        validator(wrong_venue, expected_code_hash="code-v1", expected_lock_hash="lock-v1")



def test_oracle_paper_candidate_set_validates_multiple_unique_exact_source_candidates():
    first = paper_candidate_manifest()
    raw_second = dict(first["candidate"])
    raw_second["strategy_id"] = "R-oracle-paper-2"
    raw_second["entry"] = {"kind": "ema_cross", "fast_period": 5, "slow_period": 13, "trade_size": "0.01"}
    second_candidate = StrategyGenome(**raw_second)
    second = dict(first)
    second["candidate"] = second_candidate.canonical_payload()
    second["strategy_id"] = second_candidate.strategy_id
    second["genome_hash"] = second_candidate.genome_hash

    candidates = oracle_module.validate_paper_candidate_manifests(
        [first, second],
        expected_code_hash="code-v1",
        expected_lock_hash="lock-v1",
    )

    assert [candidate.strategy_id for candidate in candidates] == [
        "R-oracle-paper",
        "R-oracle-paper-2",
    ]


def test_oracle_paper_candidate_set_fails_closed_on_invalid_or_duplicate_members():
    validator = oracle_module.validate_paper_candidate_manifests
    manifest = paper_candidate_manifest()

    for payloads in (None, {}, "not-a-list", []):
        with pytest.raises((TypeError, ValueError), match="candidate|list|non-empty"):
            validator(payloads, expected_code_hash="code-v1", expected_lock_hash="lock-v1")

    stale = dict(manifest)
    stale["code_hash"] = "stale"
    with pytest.raises(ValueError, match="code_hash"):
        validator([manifest, stale], expected_code_hash="code-v1", expected_lock_hash="lock-v1")

    with pytest.raises(ValueError, match="duplicate.*strategy|strategy.*duplicate"):
        validator([manifest, dict(manifest)], expected_code_hash="code-v1", expected_lock_hash="lock-v1")

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
    assert "systemctl enable mastertrd.service" not in script
    assert "/etc/systemd/system/mastertrd-paper@.service" in script
    assert "logrotate" in script
    assert "mastertrd-health" in script
    assert "chmod 600 /etc/mastertrd/mastertrd.env" in script
    assert "ORACLE_ENABLED=false" in script



def test_oracle_paper_systemd_template_isolates_each_strategy_environment():
    unit = oracle_module.render_paper_systemd_template(spec())
    assert "EnvironmentFile=/etc/mastertrd/paper/%i.env" in unit
    assert "ExecStart=/opt/mastertrd/.venv/bin/python -m mastertrd.live_node" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ReadWritePaths=/opt/mastertrd /var/lib/mastertrd /var/log/mastertrd" in unit


def test_oracle_bootstrap_installs_multi_instance_paper_service_and_rotation_templates():
    script = render_bootstrap_script(spec())
    assert "/etc/mastertrd/paper" in script
    assert "/etc/systemd/system/mastertrd-paper@.service" in script
    assert "/etc/systemd/system/mastertrd-paper-rotate@.service" in script
    assert "/etc/systemd/system/mastertrd-paper-rotate@.timer" in script
    assert "mastertrd-paper-rotate-request" in script
    assert 'ENV_FILE="/etc/mastertrd/paper/${instance}.env"' in script
    assert "systemctl enable mastertrd.service" not in script


def test_oracle_health_script_accepts_only_mastertrd_paper_instance_units():
    script = oracle_module.render_health_script()
    assert 'service_name="${1:-mastertrd.service}"' in script
    assert "mastertrd-paper@*.service" in script
    assert 'systemctl is-active --quiet "$service_name"' in script

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
    dispatch = triggers["workflow_dispatch"]
    assert dispatch["inputs"]["paper_candidates_json"]["required"] is True
    assert "paper_candidate_manifest_json" not in dispatch["inputs"]
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


def test_oracle_deploy_reads_root_owned_safety_env_with_sudo():
    text = (ROOT / ".github" / "workflows" / "oracle-deploy.yml").read_text(encoding="utf-8")
    assert "sudo awk -F=" in text


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


def test_oracle_deploy_installs_only_identity_checked_public_paper_candidate_set():
    text = (ROOT / ".github" / "workflows" / "oracle-deploy.yml").read_text(encoding="utf-8")
    assert "paper_candidates_json" in text
    assert "validate_paper_candidate_manifests" in text
    assert "/var/lib/mastertrd/paper/$GITHUB_SHA" in text
    assert "/etc/mastertrd/paper" in text
    assert "MASTERTRD_PAPER_ROTATE_AFTER_SECONDS=600" in text
    assert "mastertrd-paper@" in text
    assert "mastertrd-paper-rotate@" in text
    assert "LIVE_TRADING_ENABLED=false" in text
