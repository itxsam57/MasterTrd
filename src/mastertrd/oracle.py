from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .genome import StrategyGenome


@dataclass(frozen=True, slots=True)
class OracleDeploymentSpec:
    app_dir: str
    service_user: str
    python_bin: str
    module: str
    env_file: str

    def __post_init__(self) -> None:
        for name, value in (
            ("app_dir", self.app_dir),
            ("service_user", self.service_user),
            ("python_bin", self.python_bin),
            ("module", self.module),
            ("env_file", self.env_file),
        ):
            if not value or not value.strip():
                raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True, slots=True)
class OracleDeploymentBundle:
    env_file: str
    env_template: str
    systemd_unit: str
    health_command: str
    health_script: str
    logrotate_config: str
    bootstrap_script: str


def _required_manifest_string(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def validate_paper_candidate_manifest(
    payload: Mapping[str, object],
    *,
    expected_code_hash: str,
    expected_lock_hash: str,
) -> StrategyGenome:
    """Validate a public-safe ResearchJob PAPER handoff for Oracle execution."""
    if not expected_code_hash:
        raise ValueError("expected_code_hash is required")
    if not expected_lock_hash:
        raise ValueError("expected_lock_hash is required")

    raw_candidate = payload.get("candidate")
    if not isinstance(raw_candidate, Mapping):
        raise ValueError("candidate is required")
    try:
        candidate = StrategyGenome(**dict(raw_candidate))
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate is invalid") from exc

    strategy_id = _required_manifest_string(payload, "strategy_id")
    genome_hash = _required_manifest_string(payload, "genome_hash")
    code_hash = _required_manifest_string(payload, "code_hash")
    _required_manifest_string(payload, "dataset_hash")
    lock_hash = _required_manifest_string(payload, "lock_hash")

    if strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")
    if code_hash != expected_code_hash:
        raise ValueError("code_hash does not match deployed source")
    if lock_hash != expected_lock_hash:
        raise ValueError("lock_hash does not match deployed dependency lock")
    if len(candidate.instruments) != 1:
        raise ValueError("Oracle PAPER runtime currently requires one instrument")

    instrument = str(candidate.instruments[0]).strip().upper()
    if not instrument.endswith(".BINANCE"):
        raise ValueError("Oracle PAPER runtime currently requires a BINANCE instrument")
    return candidate



def validate_paper_candidate_manifests(
    payloads: object,
    *,
    expected_code_hash: str,
    expected_lock_hash: str,
) -> tuple[StrategyGenome, ...]:
    """Validate one atomic Oracle PAPER candidate deployment set."""
    if not isinstance(payloads, list):
        raise TypeError("paper candidate manifests must be a list")
    if not payloads:
        raise ValueError("paper candidate manifest list must be non-empty")

    candidates: list[StrategyGenome] = []
    strategy_ids: set[str] = set()
    genome_hashes: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, Mapping):
            raise TypeError("paper candidate manifest must be an object")
        candidate = validate_paper_candidate_manifest(
            payload,
            expected_code_hash=expected_code_hash,
            expected_lock_hash=expected_lock_hash,
        )
        if candidate.strategy_id in strategy_ids:
            raise ValueError(f"duplicate strategy_id in PAPER candidate set: {candidate.strategy_id}")
        if candidate.genome_hash in genome_hashes:
            raise ValueError(f"duplicate genome_hash in PAPER candidate set: {candidate.genome_hash}")
        strategy_ids.add(candidate.strategy_id)
        genome_hashes.add(candidate.genome_hash)
        candidates.append(candidate)
    return tuple(candidates)

def render_env_template() -> str:
    return """# MasterTrd host environment template
# Keep secrets out of git. Populate credential values only on the target host
# or through an approved secret-delivery mechanism.
MASTERTRD_MODE=PAPER
LIVE_TRADING_ENABLED=false
ORACLE_ENABLED=false
MASTERTRD_CANDIDATE_MANIFEST=/var/lib/mastertrd/paper-candidate.json
MASTERTRD_SESSION_STATE=/var/lib/mastertrd/paper-session.json
MASTERTRD_PAPER_ARCHIVE=/var/lib/mastertrd/paper/reports.json
MASTERTRD_PAPER_HISTORY_DIR=/var/lib/mastertrd/paper/sessions
MASTERTRD_PAPER_ROTATION_REQUEST=/var/lib/mastertrd/paper/rotate.request
MASTERTRD_PAPER_ROTATE_AFTER_SECONDS=86400
MASTERTRD_CODE_HASH=
MASTERTRD_PUBLIC_FEED_FIXTURE=
MASTERTRD_SESSION_NONCE=
MASTERTRD_PAPER_START_NS=
BINANCE_DEMO_API_KEY=
BINANCE_DEMO_API_SECRET=
BINANCE_DEMO_ACCOUNT_ID=
BINANCE_TESTNET_API_KEY=
BINANCE_TESTNET_API_SECRET=
BINANCE_TESTNET_ACCOUNT_ID=
BINANCE_LIVE_API_KEY=
BINANCE_LIVE_API_SECRET=
BINANCE_LIVE_ACCOUNT_ID=
"""


def render_systemd_unit(spec: OracleDeploymentSpec) -> str:
    return f"""[Unit]
Description=MasterTrd execution node
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={spec.service_user}
WorkingDirectory={spec.app_dir}
EnvironmentFile={spec.env_file}
ExecStart={spec.python_bin} -m {spec.module}
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
KillSignal=SIGINT
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ReadWritePaths={spec.app_dir} /var/lib/mastertrd /var/log/mastertrd
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def render_health_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
systemctl is-active --quiet mastertrd.service
systemctl show mastertrd.service --property=NRestarts --value
"""


def render_logrotate_config() -> str:
    return """/var/log/mastertrd/*.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
"""


def render_bootstrap_script(spec: OracleDeploymentSpec) -> str:
    env_template = render_env_template().rstrip()
    unit = render_systemd_unit(spec).rstrip()
    health = render_health_script().rstrip()
    logrotate = render_logrotate_config().rstrip()
    return f'''#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "MasterTrd Oracle adapter requires Linux" >&2
  exit 2
fi

ARCH="$(uname -m)"
case "${{ARCH}}" in
  aarch64|arm64|x86_64|amd64) ;;
  *) echo "Unsupported architecture: ${{ARCH}}" >&2; exit 3 ;;
esac

if [[ "${{EUID}}" -ne 0 ]]; then
  echo "Run bootstrap as root" >&2
  exit 4
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv git curl logrotate ca-certificates

id -u {spec.service_user} >/dev/null 2>&1 || useradd --system --home {spec.app_dir} --shell /usr/sbin/nologin {spec.service_user}
mkdir -p {spec.app_dir} /etc/mastertrd /var/lib/mastertrd /var/lib/mastertrd/paper /var/log/mastertrd
chown -R {spec.service_user}:{spec.service_user} {spec.app_dir} /var/lib/mastertrd /var/log/mastertrd

if [[ ! -f {spec.env_file} ]]; then
cat > {spec.env_file} <<'MASTERTRD_ENV'
{env_template}
MASTERTRD_ENV
fi
chown root:root {spec.env_file}
chmod 600 {spec.env_file}

cat > /etc/systemd/system/mastertrd.service <<'MASTERTRD_SERVICE'
{unit}
MASTERTRD_SERVICE

cat > /usr/local/bin/mastertrd-health <<'MASTERTRD_HEALTH'
{health}
MASTERTRD_HEALTH
chmod 755 /usr/local/bin/mastertrd-health

cat > /usr/local/bin/mastertrd-paper-rotate-request <<'MASTERTRD_ROTATE_REQUEST'
#!/usr/bin/env bash
set -euo pipefail
ENV_FILE={spec.env_file}
[[ -r "$ENV_FILE" ]] || exit 0

mode="$(awk -F= '$1=="MASTERTRD_MODE" {{print $2}}' "$ENV_FILE" | tail -n1)"
live="$(awk -F= '$1=="LIVE_TRADING_ENABLED" {{print $2}}' "$ENV_FILE" | tail -n1)"
[[ "${{mode^^}}" == "PAPER" ]] || exit 0
[[ "${{live,,}}" != "true" ]] || exit 0

state_path="$(awk -F= '$1=="MASTERTRD_SESSION_STATE" {{print substr($0, index($0, "=") + 1)}}' "$ENV_FILE" | tail -n1)"
request_path="$(awk -F= '$1=="MASTERTRD_PAPER_ROTATION_REQUEST" {{print substr($0, index($0, "=") + 1)}}' "$ENV_FILE" | tail -n1)"
rotate_after="$(awk -F= '$1=="MASTERTRD_PAPER_ROTATE_AFTER_SECONDS" {{print $2}}' "$ENV_FILE" | tail -n1)"
[[ -n "$state_path" && -n "$request_path" ]] || exit 0
case "$rotate_after" in
  ''|*[!0-9]*) exit 0 ;;
esac
(( rotate_after > 0 )) || exit 0
[[ -f "$state_path" ]] || exit 0

started_ns="$({spec.python_bin} - "$state_path" <<'MASTERTRD_ROTATE_PY'
import sys
from mastertrd.paper_session import JsonPaperSessionStore

journal = JsonPaperSessionStore(sys.argv[1]).load()
if journal.finalized_report is None:
    print(journal.started_ns)
MASTERTRD_ROTATE_PY
)"
[[ -n "$started_ns" ]] || exit 0
now_ns="$(date +%s%N)"
(( now_ns >= started_ns )) || exit 0
elapsed_seconds=$(( (now_ns - started_ns) / 1000000000 ))
(( elapsed_seconds >= rotate_after )) || exit 0

if [[ ! -e "$request_path" ]]; then
  install -o {spec.service_user} -g {spec.service_user} -m 600 /dev/null "$request_path"
fi
MASTERTRD_ROTATE_REQUEST
chmod 755 /usr/local/bin/mastertrd-paper-rotate-request

cat > /etc/systemd/system/mastertrd-paper-rotate.service <<'MASTERTRD_ROTATE_SERVICE'
[Unit]
Description=Request MasterTrd in-process PAPER evidence rotation
After=mastertrd.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/mastertrd-paper-rotate-request
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/mastertrd
MASTERTRD_ROTATE_SERVICE

cat > /etc/systemd/system/mastertrd-paper-rotate.timer <<'MASTERTRD_ROTATE_TIMER'
[Unit]
Description=Check whether MasterTrd PAPER evidence window should rotate

[Timer]
OnBootSec=1m
OnUnitActiveSec=1m
Persistent=true
Unit=mastertrd-paper-rotate.service

[Install]
WantedBy=timers.target
MASTERTRD_ROTATE_TIMER

cat > /etc/logrotate.d/mastertrd <<'MASTERTRD_LOGROTATE'
{logrotate}
MASTERTRD_LOGROTATE
chmod 644 /etc/logrotate.d/mastertrd

systemctl daemon-reload
systemctl enable mastertrd.service
systemctl enable --now mastertrd-paper-rotate.timer

echo "Oracle adapter installed with safe defaults."
echo "The host environment file is preserved on repeat runs; repository deployment never overwrites credentials."
echo "PAPER evidence rotation is requested in-process and never restarts the execution engine."
echo "Use the identity-checked Oracle Deploy workflow to configure and start PAPER."
'''


def render_oracle_bundle(spec: OracleDeploymentSpec) -> OracleDeploymentBundle:
    return OracleDeploymentBundle(
        env_file=spec.env_file,
        env_template=render_env_template(),
        systemd_unit=render_systemd_unit(spec),
        health_command="/usr/local/bin/mastertrd-health",
        health_script=render_health_script(),
        logrotate_config=render_logrotate_config(),
        bootstrap_script=render_bootstrap_script(spec),
    )