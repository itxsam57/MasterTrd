# MasterTrd Operations Runbook

This runbook covers local development and the persistent Linux execution node. It does not weaken the Promotion Governor: deployment readiness and strategy LIVE eligibility are separate gates.

## Safety invariants

- `LIVE_TRADING_ENABLED=false` is the default and must remain false for RESEARCH, BACKTEST, PAPER, DEMO, and TESTNET work.
- `ORACLE_ENABLED=false` is the default. Oracle deployment is permitted only when both the GitHub Environment variable and `/etc/mastertrd/mastertrd.env` explicitly contain `ORACLE_ENABLED=true`.
- Exchange API keys must never have withdrawal permission.
- Exchange credentials, account state, balances, positions, and private payloads are never committed to git.
- NautilusTrader remains the authoritative execution engine.
- Only the Promotion Governor may advance a strategy to `LIVE_ELIGIBLE`.
- `asset_transfer` remains a separate mandatory robust-promotion gate.
- Real TESTNET smoke evidence cannot be replaced by a simulated callback or PAPER result.
- GitHub Actions never acts as the persistent low-latency LIVE execution server.

## Owner inputs

The repository is deployable without embedding any secret, but an actual Oracle host deployment requires the following owner-supplied GitHub Environment `oracle` values:

- Variable `ORACLE_ENABLED=true`.
- Secret `ORACLE_HOST`: Oracle VM DNS name or IP address.
- Secret `ORACLE_SSH_USER`: SSH user with the approved `sudo` capability needed by the bootstrap.
- Secret `ORACLE_SSH_KEY`: private SSH key used only by the deployment job.
- Secret `ORACLE_KNOWN_HOSTS`: pinned OpenSSH known-hosts entry for that VM. Do not replace this with disabled host verification.

The host itself requires `/etc/mastertrd/mastertrd.env`, owned by root and not stored in git. Set only the credentials required for the runtime mode being used. Relevant names are:

- DEMO: `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_API_SECRET`, `BINANCE_DEMO_ACCOUNT_ID`.
- TESTNET: `BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_API_SECRET`, `BINANCE_TESTNET_ACCOUNT_ID`.
- LIVE: `BINANCE_LIVE_API_KEY`, `BINANCE_LIVE_API_SECRET`, `BINANCE_LIVE_ACCOUNT_ID`.

The GitHub Environment `testnet` separately needs the TESTNET names above to execute credential-gated TESTNET checks. Missing credentials are an owner-input blocker and must be reported as such; they are not a PASS.

## Windows development

Windows is a development/test surface, not the persistent LIVE node. From PowerShell in a clean checkout:

```powershell
python -m pip install --disable-pip-version-check uv
uv lock --check
uv sync --locked --all-extras
uv pip check
uv run pytest -q
```

For safe local runtime configuration, keep:

```powershell
$env:MASTERTRD_MODE = "PAPER"
$env:LIVE_TRADING_ENABLED = "false"
$env:ORACLE_ENABLED = "false"
```

`python -m mastertrd.live_node` uses the repository-owned `build_execution_runtime` factory. PAPER needs no exchange execution credential; DEMO/TESTNET/LIVE still fail closed on their mode-specific credential and safety gates.

### Required persistent-runtime inputs

The mode flags alone are not enough to start the persistent execution process. Before invoking `python -m mastertrd.live_node`, provide an approved StrategyGenome JSON file through `MASTERTRD_CANDIDATE_MANIFEST`. The manifest is the exact candidate the runtime is allowed to execute; do not point this variable at a generic system-smoke or unrelated candidate.

PAPER additionally requires:

- `MASTERTRD_SESSION_STATE`: writable JSON state path used for crash-safe PAPER journaling/recovery.
- `MASTERTRD_CODE_HASH`: exact source identity bound into the PAPER session.
- optional `MASTERTRD_PUBLIC_FEED_FIXTURE`, `MASTERTRD_SESSION_NONCE`, and `MASTERTRD_PAPER_START_NS` for deterministic/offline replay.

DEMO, TESTNET, and LIVE additionally require `MASTERTRD_BINANCE_PRODUCT` set explicitly to `SPOT`, `USD_M`, or `COIN_M`, plus that mode's `BINANCE_<MODE>_*` credentials. No mode silently selects a product or falls back to another credential namespace.

The checked-in `.env.example` lists these names but is not automatically loaded by Python; export them into the process environment or supply them through the service/GitHub Environment. Empty placeholders intentionally fail closed.

## Linux production node

The canonical persistent node is a Linux host (Oracle free-tier adapter supported on arm64/aarch64 and amd64/x86_64). The deployment bundle renders:

- systemd unit `/etc/systemd/system/mastertrd.service` running `python -m mastertrd.live_node`;
- external environment file `/etc/mastertrd/mastertrd.env`;
- health command `/usr/local/bin/mastertrd-health`;
- logrotate policy `/etc/logrotate.d/mastertrd`;
- bootstrap script with restart-on-failure and OS/architecture checks.

The service uses `Restart=on-failure`, `NoNewPrivileges=true`, a restrictive umask, systemd filesystem protections, and journal output. Repository deployment never overwrites an existing host environment file.

### Initial Oracle setup

1. Create the GitHub Environment `oracle` and add the exact owner inputs above.
2. Keep its `ORACLE_ENABLED` variable false until the VM address, SSH key, and pinned known-host entry are verified.
3. On the VM, create/edit `/etc/mastertrd/mastertrd.env`. Start from the generated template, then set only the runtime flags and mode-specific credentials required for the chosen non-LIVE mode.
4. Run and validate PAPER or DEMO first.
5. Set the host file to `ORACLE_ENABLED=true` only after the preceding checks are complete.
6. Set GitHub Environment variable `ORACLE_ENABLED=true` and manually dispatch **Oracle Deploy**. There is no schedule, push, or automatic LIVE deployment trigger.

The deploy workflow checks out the exact GitHub SHA, verifies `uv.lock`, installs from the lock, uses pinned SSH host trust, deploys the exact SHA, preserves the external host environment file, and runs `mastertrd-health` after a non-LIVE restart. It refuses an automated restart when `MASTERTRD_MODE=LIVE`.

## Runtime modes

### PAPER

Set:

```text
MASTERTRD_MODE=PAPER
LIVE_TRADING_ENABLED=false
MASTERTRD_CANDIDATE_MANIFEST=/absolute/path/to/approved-candidate.json
MASTERTRD_SESSION_STATE=/var/lib/mastertrd/paper-session.json
MASTERTRD_CODE_HASH=<exact-deployed-git-sha>
```

PAPER never requires exchange execution credentials. Use it for persistent runtime recovery, journaling, reconciliation logic, and forward-paper evidence. `mastertrd.live_node` constructs the canonical repository-owned PAPER runtime directly.

### DEMO

Set:

```text
MASTERTRD_MODE=DEMO
LIVE_TRADING_ENABLED=false
MASTERTRD_CANDIDATE_MANIFEST=/absolute/path/to/approved-candidate.json
MASTERTRD_BINANCE_PRODUCT=SPOT
```

Populate only the `BINANCE_DEMO_*` credential set. Verify node preflight, exchange connectivity, reconciliation, and kill behavior. DEMO evidence cannot substitute for required TESTNET evidence when the Promotion Governor requires TESTNET.

### TESTNET

Set:

```text
MASTERTRD_MODE=TESTNET
LIVE_TRADING_ENABLED=false
MASTERTRD_CANDIDATE_MANIFEST=/absolute/path/to/approved-candidate.json
MASTERTRD_BINANCE_PRODUCT=SPOT
```

Populate only `BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_API_SECRET`, and `BINANCE_TESTNET_ACCOUNT_ID`. The key must have no withdrawal permission. Run the manual **Testnet Smoke** workflow after the `testnet` GitHub Environment is configured.

The required live-eligibility bundle remains fail-closed: risk review, reconciliation, kill-switch proof, and a real venue-minimum-notional TESTNET smoke must share the candidate/code/dataset identity. If a concrete real test-order submission adapter or credential is unavailable, report `BLOCKED_OWNER_INPUT`/`CREDENTIALS_UNAVAILABLE` rather than creating synthetic evidence.

### LIVE

LIVE is deliberately a separate owner-controlled action. Before changing the host to LIVE, all of the following must already be true:

- the candidate is `LIVE_ELIGIBLE` through the Promotion Governor;
- real TESTNET smoke, reconciliation, kill-switch, and risk-review evidence pass and bind to the correct identities;
- the separate `asset_transfer` requirement has not been bypassed;
- the LIVE exchange key has no withdrawal permission and is restricted as tightly as the venue supports;
- position/notional/drawdown/daily-loss/order-rate/API-health/reconciliation limits have been reviewed;
- the owner has reviewed the exact deployed SHA and current environment file.

Then set on the host, deliberately:

```text
MASTERTRD_MODE=LIVE
LIVE_TRADING_ENABLED=true
ORACLE_ENABLED=true
MASTERTRD_CANDIDATE_MANIFEST=/absolute/path/to/governor-approved-live-candidate.json
MASTERTRD_BINANCE_PRODUCT=SPOT
```

The Oracle Deploy workflow will deploy an exact SHA but will **not** restart a LIVE service. After the owner review, start or restart it from the host:

```bash
sudo systemctl restart mastertrd.service
sudo /usr/local/bin/mastertrd-health
```

To leave LIVE, stop the service first, change `LIVE_TRADING_ENABLED=false`, change `MASTERTRD_MODE` to PAPER/DEMO/TESTNET as appropriate, then restart only after preflight.

## Health and logs

Primary health check:

```bash
sudo /usr/local/bin/mastertrd-health
```

Service status and recent logs:

```bash
sudo systemctl status mastertrd.service --no-pager
sudo journalctl -u mastertrd.service -n 200 --no-pager
sudo journalctl -u mastertrd.service -f
```

The bundle also provisions `/var/log/mastertrd` and `/etc/logrotate.d/mastertrd` for any file-based operator/export logs written there; logrotate keeps 14 compressed daily rotations. Sensitive raw account payloads must not be written to those logs.

## Emergency kill

For an owner-level **emergency kill**, stop the persistent node first:

```bash
sudo systemctl stop mastertrd.service
```

Then verify it is inactive:

```bash
sudo systemctl is-active mastertrd.service
```

If capital may be at risk, separately use the exchange's authenticated controls to cancel unexpected open orders and disable/revoke the API key. Do not depend on the application process being alive to revoke exchange access.

Before any restart after an emergency:

1. set `LIVE_TRADING_ENABLED=false` in `/etc/mastertrd/mastertrd.env`;
2. use PAPER or TESTNET while diagnosing;
3. reconcile balances, positions, open orders, and fills against the venue;
4. identify and fix the cause;
5. rerun the kill-switch and reconciliation evidence gates;
6. require fresh owner review before returning to LIVE.

The in-process `RiskRuntime` system kill remains the automatic order-blocking mechanism; `systemctl stop` is the independent operator kill path.

## Recovery

After a VM reboot or process failure:

1. check `systemctl status` and `journalctl`;
2. run `mastertrd-health` and inspect the service restart count;
3. confirm the exact deployed git SHA with `git -C /opt/mastertrd rev-parse HEAD`;
4. confirm `uv lock --check` and dependency health;
5. keep LIVE disabled until engine state and venue state reconcile;
6. resume from the durable runtime/paper journals rather than replaying already-recorded market events;
7. if reconciliation fails, keep the system killed and investigate before restart.

Never delete journals merely to make recovery pass.

## Rollback

Rollback uses a previously verified exact SHA, not an unpinned branch tip.

```bash
sudo systemctl stop mastertrd.service
sudo -u mastertrd git -C /opt/mastertrd fetch origin <VERIFIED_SHA>
sudo -u mastertrd git -C /opt/mastertrd checkout --detach <VERIFIED_SHA>
sudo -u mastertrd bash -c 'cd /opt/mastertrd && .uv-tool/bin/uv lock --check && .uv-tool/bin/uv sync --locked --all-extras && .uv-tool/bin/uv pip check'
```

Keep `LIVE_TRADING_ENABLED=false` during rollback verification. Run the cumulative tests/preflight appropriate to the node, then restart in PAPER/TESTNET. Returning to LIVE requires the same owner review as a forward deployment.

## Secret rotation

1. Stop the service if rotating a key used by the active execution mode.
2. Create the replacement venue key with no withdrawal permission and the narrowest supported permissions/IP restrictions.
3. Update only `/etc/mastertrd/mastertrd.env` (and the corresponding GitHub Environment secret for TESTNET when applicable). Never commit the value.
4. Set file ownership/permissions back to the bundle standard and verify no shell history/log contains the secret.
5. Revoke the old key at the exchange.
6. Start in TESTNET/DEMO where applicable, rerun preflight/reconciliation, then restore the intended mode only after validation.

SSH deployment keys and `ORACLE_KNOWN_HOSTS` should also be rotated when host access changes. GitHub's Oracle deployment secrets are transport credentials only; exchange LIVE secrets are intentionally not copied by `oracle-deploy.yml`.

## Vercel boundary

Vercel is unsuitable for the persistent low-latency execution node: its request/serverless lifecycle is not the process model required by the long-running execution runtime, reconciliation loop, durable session ownership, and kill semantics. Do not use Vercel to host `mastertrd.live_node`.

A future **read-only** dashboard or API may be hosted on Vercel if it exposes sanitized observability only and cannot submit orders, mutate strategy lifecycle state, receive raw exchange secrets, or bypass the Promotion Governor.
