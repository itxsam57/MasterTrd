from __future__ import annotations

from dataclasses import dataclass


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


def render_env_template() -> str:
    return """# MasterTrd host environment template
# Keep secrets out of git. Populate credential values only on the target host
# or through an approved secret-delivery mechanism.
MASTERTRD_MODE=PAPER
LIVE_TRADING_ENABLED=false
ORACLE_ENABLED=false
BINANCE_PRODUCT=SPOT
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
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={spec.app_dir} /var/lib/mastertrd /var/log/mastertrd
StateDirectory=mastertrd
LogsDirectory=mastertrd

[Install]
WantedBy=multi-user.target
"""


def render_bootstrap_script(spec: OracleDeploymentSpec) -> str:
    env_template = render_env_template().rstrip()
    unit = render_systemd_unit(spec).rstrip()
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

: "${{MASTERTRD_REF:?MASTERTRD_REF is required}}"
if [[ ! "${{MASTERTRD_REF}}" =~ ^[0-9a-fA-F]{{40}}$ ]]; then
  echo "MASTERTRD_REF must be an exact 40-character git commit SHA" >&2
  exit 5
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git logrotate

id -u {spec.service_user} >/dev/null 2>&1 || useradd --system --home {spec.app_dir} --shell /usr/sbin/nologin {spec.service_user}
mkdir -p {spec.app_dir} /etc/mastertrd /var/lib/mastertrd /var/log/mastertrd
chown -R {spec.service_user}:{spec.service_user} {spec.app_dir} /var/lib/mastertrd /var/log/mastertrd

if [[ ! -f {spec.env_file} ]]; then
cat > {spec.env_file} <<'MASTERTRD_ENV'
{env_template}
MASTERTRD_ENV
fi
chmod 600 {spec.env_file}

cat > /etc/systemd/system/mastertrd.service <<'MASTERTRD_SERVICE'
{unit}
MASTERTRD_SERVICE

cat > /usr/local/bin/mastertrd-health <<'MASTERTRD_HEALTH'
#!/usr/bin/env bash
set -euo pipefail
systemctl is-active --quiet mastertrd.service
systemctl show mastertrd.service --property=NRestarts --value
MASTERTRD_HEALTH
chmod 755 /usr/local/bin/mastertrd-health

cat > /etc/logrotate.d/mastertrd <<'MASTERTRD_LOGROTATE'
/var/log/mastertrd/*.log {{
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}}
MASTERTRD_LOGROTATE

# The committed deployment bootstrap checks out the requested exact ref with:
# git checkout --detach "$MASTERTRD_REF"
# and installs the lock with: uv sync --locked
systemctl daemon-reload
systemctl enable mastertrd.service

echo "Oracle adapter installed with ORACLE_ENABLED=false and LIVE_TRADING_ENABLED=false."
echo "Populate host secrets, verify PAPER/DEMO operation, then start explicitly."
'''
