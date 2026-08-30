# MasterTrd

MasterTrd is a zero-cost-first autonomous quantitative research, validation, paper/demo/testnet, and controlled live-trading platform. `MASTER_PLAN.md` is the canonical product specification and NautilusTrader is the sole authoritative execution engine.

## Safety defaults

- `MASTERTRD_MODE=PAPER`
- `LIVE_TRADING_ENABLED=false`
- `ORACLE_ENABLED=false`
- Exchange and SSH secrets never belong in git.
- Trading API keys must have **no withdrawal permission**.
- There is no automatic PAPER/DEMO/TESTNET-to-LIVE fallback.
- No strategy becomes live-eligible without the Promotion Governor and required validation evidence.

## Implementation status

The completion branch contains the research/generation stack, deterministic genome and result contracts, multi-stage robustness/hidden/specialist validation, research memory, persistent paper state, Nautilus backtest/paper/exchange bridges, risk and promotion governors, fail-closed persistent execution service, and portable Oracle Linux ARM64/x86_64 deployment assets.

Credential-dependent Binance DEMO/TESTNET venue smoke tests and a real Oracle-host smoke are intentionally **OWNER_INPUT_REQUIRED** until credentials/host details are supplied through secrets. They are not represented as passed without external evidence. See `docs/ACCEPTANCE.md`.

## Reproducible local install

Python 3.13 and `uv` are the supported path.

```bash
python -m pip install --disable-pip-version-check uv
uv lock --check
uv sync --locked --all-extras
uv pip check
uv run pytest -q
```

For the lightweight core only:

```bash
uv sync --locked --extra dev
uv run pytest -q
```

## Safe PAPER preflight

PAPER requires no exchange credentials and cannot construct an exchange node.

```bash
MASTERTRD_MODE=PAPER LIVE_TRADING_ENABLED=false uv run python - <<'PY'
import os
from mastertrd.live_node import NodeReadiness, preflight_node
from mastertrd.runtime import RuntimeConfig
runtime = RuntimeConfig.from_env(dict(os.environ))
assert preflight_node(runtime, os.environ) is NodeReadiness.PAPER_READY
print('PAPER preflight: OK')
PY
```

## Runtime modes

`RESEARCH`, `BACKTEST`, `PAPER`, `DEMO`, `TESTNET`, `LIVE`.

DEMO/TESTNET/LIVE use mode-specific Binance credential namespaces. LIVE additionally requires both `MASTERTRD_MODE=LIVE` and `LIVE_TRADING_ENABLED=true`; otherwise startup fails closed.

## Oracle / Linux deployment

Deployment assets are under `deploy/oracle/` and support Linux ARM64/Ampere A1 and x86_64. The GitHub workflow `.github/workflows/oracle-deploy.yml` is **manual-only**, takes an exact 40-character commit SHA, uses environment secrets, installs that detached SHA from `uv.lock`, and deliberately leaves `mastertrd.service` stopped.

Required GitHub Environment secrets for the `oracle-production` environment are `ORACLE_HOST`, `ORACLE_USER`, and `ORACLE_SSH_KEY`. Exchange secrets belong in `/etc/mastertrd/mastertrd.env` on the host or another approved secret-delivery mechanism, never in the repository.

After a manual deployment, verify the exact installed SHA and safe environment before explicitly starting the service. Do not enable LIVE as part of deployment.

## Verification

The final cumulative gate is `.github/workflows/acceptance.yml`. It checks the lock, installs all admitted extras, validates installed dependencies, runs the cumulative suite, proves PAPER preflight isolation, and scans tracked content for forbidden secret material.

See `docs/ACCEPTANCE.md` for the definition-of-done evidence map.
