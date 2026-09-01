# MasterTrd Operations Runbook

This runbook covers local development and the persistent Linux execution node. It does not weaken the Promotion Governor: deployment readiness and strategy LIVE eligibility are separate gates.

## Safety invariants

- `LIVE_TRADING_ENABLED=false` is the default and must remain false for RESEARCH, BACKTEST, PAPER, DEMO, and TESTNET work.
- `ORACLE_ENABLED=false` is the repository default. An Oracle deployment runs only when the protected GitHub Environment `oracle` explicitly has `ORACLE_ENABLED=true`; the deploy workflow configures `ORACLE_ENABLED=true` on the host only as part of an identity-checked PAPER deployment.
- Oracle Deploy refuses automated host mutation or restart when the existing host is configured with `MASTERTRD_MODE=LIVE` or `LIVE_TRADING_ENABLED=true`.
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

The host keeps `/etc/mastertrd/mastertrd.env`, owned by root and never stored in git. Oracle Deploy updates only the non-secret PAPER runtime values it owns (`MASTERTRD_MODE`, `LIVE_TRADING_ENABLED`, `ORACLE_ENABLED`, the PAPER candidate/session paths, exact code hash, and deterministic PAPER controls). Existing exchange credential entries are preserved. Configure exchange credentials only when a later runtime mode actually requires them:

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
- persistent PAPER state directory `/var/lib/mastertrd`;
- health command `/usr/local/bin/mastertrd-health`;
- logrotate policy `/etc/logrotate.d/mastertrd`;
- bootstrap script with restart-on-failure and OS/architecture checks.

The service uses `Restart=on-failure`, `NoNewPrivileges=true`, a restrictive umask, systemd filesystem protections, journal output, and an explicit writable path for `/var/lib/mastertrd`. The bootstrap preserves an existing host environment file and its exchange credentials; Oracle Deploy changes only the validated non-secret PAPER keys described above.

### Initial Oracle PAPER setup

1. Create the protected GitHub Environment `oracle` and add the exact transport inputs listed under **Owner inputs**.
2. Keep the Environment variable `ORACLE_ENABLED=false` until the VM address, SSH key, and pinned known-host entry are verified.
3. Run **Autonomous Research** on the exact source SHA intended for deployment. Use only a genuine public-safe `PAPER` finalist manifest emitted by that exact run. The handoff contains strategy/genome/code/dataset/lock/recipe provenance but no exchange credential.
4. Set the Environment variable `ORACLE_ENABLED=true` and manually dispatch **Oracle Deploy**, passing that exact manifest as `paper_candidate_manifest_json`. There is no scheduled or push-triggered Oracle deployment.
5. Oracle Deploy recomputes the current `uv.lock` hash and rejects stale or mismatched strategy, genome, code, or dependency-lock identities. In particular, the manifest's `code_hash` must equal the workflow's exact `GITHUB_SHA`.
6. If validation succeeds, the workflow installs only the canonical StrategyGenome payload at `/var/lib/mastertrd/paper-candidate.json`, configures `/var/lib/mastertrd/paper-session.json`, binds `MASTERTRD_CODE_HASH` to the deployed SHA, forces `MASTERTRD_MODE=PAPER` and `LIVE_TRADING_ENABLED=false`, then starts the service and runs `mastertrd-health`.
7. Verify `mastertrd-health`, service status, and journal logs. Keep the node in PAPER while accumulating real forward evidence.

Oracle Deploy checks out the exact GitHub SHA, verifies `uv.lock`, installs from the lock, uses pinned SSH host trust, refuses a dirty tracked checkout, verifies the exact remote SHA, and never copies exchange credentials. If the existing host environment is LIVE-enabled, the workflow fails closed before automated mutation or restart.

A PAPER manifest is SHA-bound. After any code merge that changes the deployable source SHA, do not reuse an older research manifest merely to make deployment pass. Run research on the new exact SHA and use a newly identity-bound PAPER finalist.

## Runtime modes

### PAPER

For Oracle Deploy, the workflow configures these values after identity validation:

```text
MASTERTRD_MODE=PAPER
LIVE_TRADING_ENABLED=false
MASTERTRD_CANDIDATE_MANIFEST=/var/lib/mastertrd/paper-candidate.json
MASTERTRD_SESSION_STATE=/var/lib/mastertrd/paper-session.json
MASTERTRD_CODE_HASH=<exact-deployed-git-sha>
```

For a non-Oracle local PAPER process, equivalent absolute writable paths may be supplied manually.

PAPER never requires exchange execution credentials. Use it for persistent runtime recovery, journaling, reconciliation logic, and forward-paper evidence. `mastertrd.live_node` constructs the canonical repository-owned PAPER runtime directly and consumes real Binance public market data unless an explicit deterministic fixture is configured.

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

**Oracle Deploy is not the LIVE deployment/start mechanism.** When the existing host is configured as LIVE or `LIVE_TRADING_ENABLED=true`, the workflow refuses automated mutation and restart. After the separate owner review, deploy/start LIVE only through the documented owner-controlled host procedure. To start or restart an already reviewed LIVE checkout from the host:

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
