# MasterTrd Local Operations Runbook

MasterTrd is **local-first**. The PC running MasterTrd owns the consumer app, research workers, scheduler, market connections, PAPER state, and provider-gated trading worker. Vercel, PostHog, Neon, and GitHub-hosted Actions are not required; they may be used only as optional external services.

## Safety defaults

- `MASTERTRD_MODE=PAPER`
- `LIVE_TRADING_ENABLED=false`
- Exchange keys must have **no withdrawal permission**.
- Secrets never go in git, chat, screenshots, logs, or research artifacts.
- LIVE requires explicit provider admission, credentials, risk approval, reconciliation, recovery evidence, and Promotion Governor approval.
- There is no automatic PAPER/TESTNET-to-LIVE fallback.

## Install and start

From the repository root:

```bash
python -m pip install uv
uv lock --check
uv sync --locked --all-extras
uv pip check
uv run mastertrd status
uv run mastertrd app
```

`mastertrd app` opens the local Streamlit control plane on `127.0.0.1`. The app does not submit exchange orders directly; it delegates to the shared MasterTrd/Nautilus execution path.

Useful commands:

```bash
uv run mastertrd strategies
uv run mastertrd backtest --recipe ema-cross-fast
uv run mastertrd jobs
uv run mastertrd scheduler
```

Research jobs run in separate local processes under `artifacts/local-jobs/`. The optional scheduler runs recurring research/canary work locally, so GitHub cron is not required.

## Linux

Use a normal user-owned checkout and virtual environment. For a persistent trading worker, launch the repository-owned node from a process supervisor you control:

```bash
MASTERTRD_MODE=PAPER LIVE_TRADING_ENABLED=false \
  uv run python -m mastertrd.live_node
```

Keep the checkout, `.venv`, and writable `artifacts/` directories on local storage. Do not run the trading worker from a temporary CI runner.

## Windows

Use PowerShell from the repository root:

```powershell
$env:MASTERTRD_MODE = "PAPER"
$env:LIVE_TRADING_ENABLED = "false"
uv run mastertrd app
uv run python -m mastertrd.live_node
```

Use Windows Task Scheduler or another local supervisor only if persistent auto-start is desired. The runtime safety variables stay identical across Windows and Linux.

## PAPER

PAPER is the default operating mode and requires no exchange execution credentials. It is the required proving ground for strategy execution, risk rejection, reconciliation, restart/recovery, and multi-strategy behavior.

```bash
MASTERTRD_MODE=PAPER
LIVE_TRADING_ENABLED=false
```

PAPER evidence, session journals, research receipts, logs, and result artifacts stay local. Failed strategies and losing trials remain recorded.

## DEMO and TESTNET

DEMO/TESTNET use the same execution/risk path but require provider-specific sandbox credentials. For the currently implemented Binance TESTNET path, provide locally:

```text
BINANCE_TESTNET_API_KEY
BINANCE_TESTNET_API_SECRET
BINANCE_TESTNET_ACCOUNT_ID
```

Never copy these values into source files. Missing credentials must fail closed rather than silently falling back to another mode.

## LIVE

LIVE is deliberately harder to start. Both switches are required:

```bash
MASTERTRD_MODE=LIVE
LIVE_TRADING_ENABLED=true
```

For the currently implemented Binance LIVE credential contract, provide locally:

```text
BINANCE_LIVE_API_KEY
BINANCE_LIVE_API_SECRET
BINANCE_LIVE_ACCOUNT_ID
```

Setting these variables does **not** make a provider or strategy safe by itself. LIVE also requires provider admission, strategy promotion, pre-trade risk approval, exposure/account limits, reconciliation, restart/recovery evidence, credential isolation, and tested kill switches. First real activation must use owner-selected minimal size and strict caps.

## Credentials

Preferred order:

1. OS secret store / protected local environment injection.
2. User-owned environment file outside the repository with restrictive permissions.
3. Shell-session environment variables for temporary TESTNET checks.

Never commit `.env`, API keys, account IDs, private keys, seed phrases, balances, or private position state. Rotate a credential immediately if it appears in a terminal capture, log, repository, or chat.

## Logs and local data

Primary local locations are:

- `artifacts/local-jobs/` — research job receipts, stdout/stderr, reports.
- `artifacts/scheduler/` — scheduler state, canary receipts, scheduler logs.
- configured PAPER/session paths — execution journals and recovery state.
- DuckDB/Parquet stores — durable research/data history.

Logs must not contain exchange secrets. Keep enough disk space for historical data and backtest artifacts; local compute/storage is the practical backtesting ceiling.

## Emergency kill

For an unsafe or unknown trading state:

1. Stop the local trading worker/process immediately (`Ctrl+C` for a foreground node or stop its local supervisor service).
2. Leave `LIVE_TRADING_ENABLED=false` before any restart.
3. Inspect provider open orders/positions directly through the provider account.
4. Run reconciliation and inspect MasterTrd local journals/state.
5. Restart in PAPER first unless a reviewed LIVE recovery procedure explicitly requires otherwise.
6. Rotate API credentials if compromise is suspected.

The system-level emergency kill takes priority over strategy continuity or research jobs.

## Recovery

After a crash, reboot, network loss, or provider outage:

1. Keep LIVE disabled while diagnosing.
2. Verify the exact code revision and locked dependencies.
3. Inspect latest local session/research receipts and logs.
4. Reconcile expected orders/positions against provider state.
5. Confirm data freshness and risk state.
6. Start PAPER/TESTNET and prove normal behavior.
7. Resume LIVE only after the provider-specific recovery and Promotion Governor gates are satisfied.

Research workers may fail independently without taking down the trading worker.

## Rollback

Use git to return to a previously verified revision, then reinstall from the locked environment and run tests before starting a trading node:

```bash
git checkout <verified-sha>
uv lock --check
uv sync --locked --all-extras
uv run pytest -q
```

Do not roll back session/account state blindly. Reconciliation with the provider is authoritative before trading resumes.

## Secret rotation

When rotating TESTNET or LIVE credentials:

1. Stop the relevant trading worker.
2. Revoke/replace the provider key with withdrawal permission disabled.
3. Update only the protected local secret source.
4. Verify old credentials no longer work.
5. Start TESTNET/PAPER checks before re-enabling LIVE.

## Backups and GitHub

GitHub is for source control, code review, releases, and optional CI. Back up local DuckDB/Parquet/research artifacts separately if they matter; do not push private trading state or credentials to GitHub.

Vercel, PostHog, and Neon are optional integrations only. MasterTrd must continue operating locally when they are unavailable.
