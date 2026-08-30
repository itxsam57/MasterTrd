#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "MasterTrd Oracle deployment requires Linux" >&2
  exit 2
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  aarch64|arm64|x86_64|amd64) ;;
  *) echo "Unsupported architecture: ${ARCH}" >&2; exit 3 ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run bootstrap as root" >&2
  exit 4
fi

: "${MASTERTRD_REPO_URL:?Set MASTERTRD_REPO_URL to the git repository URL}"
: "${MASTERTRD_REF:?Set MASTERTRD_REF to the exact 40-character commit SHA}"
if [[ ! "${MASTERTRD_REF}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "MASTERTRD_REF must be an exact 40-character git commit SHA" >&2
  exit 5
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git logrotate

id -u mastertrd >/dev/null 2>&1 || useradd --system --home /opt/mastertrd --shell /usr/sbin/nologin mastertrd
install -d -o mastertrd -g mastertrd -m 0750 /opt/mastertrd /var/lib/mastertrd /var/log/mastertrd
install -d -o root -g root -m 0700 /etc/mastertrd

if [[ ! -x /usr/local/bin/uv ]]; then
  UV_INSTALL_DIR=/usr/local/bin sh -c "$(curl -LsSf https://astral.sh/uv/install.sh)"
fi

if [[ ! -d /opt/mastertrd/.git ]]; then
  rm -rf /opt/mastertrd/* /opt/mastertrd/.[!.]* /opt/mastertrd/..?* 2>/dev/null || true
  git clone --no-checkout "${MASTERTRD_REPO_URL}" /opt/mastertrd
fi

git -C /opt/mastertrd remote set-url origin "${MASTERTRD_REPO_URL}"
git -C /opt/mastertrd fetch --force --no-tags origin "${MASTERTRD_REF}"
git -C /opt/mastertrd checkout --detach "${MASTERTRD_REF}"
git -C /opt/mastertrd reset --hard "${MASTERTRD_REF}"
chown -R mastertrd:mastertrd /opt/mastertrd

runuser -u mastertrd -- env HOME=/opt/mastertrd /usr/local/bin/uv python install 3.13
runuser -u mastertrd -- env HOME=/opt/mastertrd /usr/local/bin/uv sync --locked --extra execution --python 3.13 --project /opt/mastertrd

if [[ ! -f /etc/mastertrd/mastertrd.env ]]; then
  install -o root -g root -m 0600 /opt/mastertrd/deploy/oracle/mastertrd.env.example /etc/mastertrd/mastertrd.env
fi
chmod 600 /etc/mastertrd/mastertrd.env

install -o root -g root -m 0644 /opt/mastertrd/deploy/oracle/mastertrd.service /etc/systemd/system/mastertrd.service
install -o root -g root -m 0755 /opt/mastertrd/deploy/oracle/mastertrd-health /usr/local/bin/mastertrd-health
install -o root -g root -m 0644 /opt/mastertrd/deploy/oracle/mastertrd.logrotate /etc/logrotate.d/mastertrd

systemctl daemon-reload
systemctl enable mastertrd.service

echo "MasterTrd installed at exact ref ${MASTERTRD_REF}."
echo "Service was NOT started. Safe defaults remain MASTERTRD_MODE=PAPER, ORACLE_ENABLED=false, LIVE_TRADING_ENABLED=false."
echo "Populate /etc/mastertrd/mastertrd.env and verify all safety/runtime settings before any separate operator-controlled service start."
