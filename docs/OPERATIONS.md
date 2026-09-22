# MasterTrd Local Operations Runbook

MasterTrd is **local-first**. The local PC owns the app, research workers, scheduler,
market connections, PAPER state, and provider-gated trading worker. Vercel, PostHog,
Neon, and GitHub-hosted Actions are optional and are not in the runtime critical path.

## Safety defaults

- `MASTERTRD_MODE=PAPER`
- `LIVE_TRADING_ENABLED=false`
- Exchange keys must have **no withdrawal permission**
- Secrets never go in git, chat, screenshots, logs, app settings, or research artifacts
- There is no PAPER/DEMO/TESTNET fallback to LIVE
- LIVE requires provider admission, credentials, reconciliation/recovery evidence,
  risk approval, kill-switch evidence, and Promotion Governor approval

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

Run the persistent trading worker separately:

```bash
uv run mastertrd trading
```

Other commands:

```bash
uv run mastertrd strategies
uv run mastertrd jobs
uv run mastertrd scheduler
uv run mastertrd config --mode PAPER --product SPOT
```

The app is a control/read surface. It never submits exchange orders directly.

## Backtest Lab

Backtest Lab launches isolated local worker processes under
`artifacts/local-jobs/<job-id>/`. Matrix dimensions include executable strategy
recipes, admitted instruments, supported timeframes, seeds, and history horizon.

Every cell uses the normal ResearchBrain path; the UI does not offer a switch to bypass
robustness, hidden/OOS, transfer, cost/slippage, or required specialist validation.

Each job keeps:

- `receipt.json`
- `stdout.log` and `stderr.log`
- `research/research.duckdb`
- `research/research-report.json`
- `research/public-data/` data/provenance artifacts, including Parquet where produced

Failed and losing trials remain visible in the app.

## PAPER and shared portfolios

PAPER is credential-free and is the safe default.

Research output may contain public-safe `paper_candidates` only for finalists that
reached `StrategyState.PAPER`. In the Trading tab, select at least two validated
finalists and choose **Prepare shared PAPER portfolio**.

MasterTrd then verifies:

1. each handoff explicitly says `state=PAPER`;
2. strategy/genome identity matches the embedded StrategyGenome;
3. every finalist uses the current code identity;
4. every finalist uses the current `uv.lock` hash.

The app writes a non-secret portfolio manifest and session path under
`artifacts/trading/`, then stores only these safe settings outside the repository in
`~/.mastertrd/runtime.json` by default:

```text
MASTERTRD_MODE=PAPER
LIVE_TRADING_ENABLED=false
MASTERTRD_BINANCE_PRODUCT=SPOT
MASTERTRD_PORTFOLIO_MANIFEST=<local path>
MASTERTRD_SESSION_STATE=<local path>
MASTERTRD_CODE_HASH=<exact code identity>
MASTERTRD_PAPER_ARCHIVE=<per-strategy archive base>
MASTERTRD_PAPER_HISTORY_DIR=<finalized session history directory>
MASTERTRD_PAPER_ROTATION_REQUEST=<local rotation request marker>
```

Start or restart:

```bash
uv run mastertrd trading
```

The worker uses one Nautilus sandbox account/engine and one shared risk runtime for the
portfolio. Per-strategy journals remain evidence views inside one atomic portfolio
state. Mixed timeframes share one public Binance websocket with exact kline
subscriptions and separate closed-bar completeness trackers.

To close a forward-evidence window, use **Close PAPER evidence window** in the Trading
tab. The app writes only a local request marker. The trading worker waits until the
shared account has no open orders or positions, finalizes every strategy journal,
archives one provenance-verified PaperForwardReport per strategy, and atomically
opens fresh portfolio sessions without restarting Nautilus. Numeric promotion policy
is deliberately not invented by the app; the existing Promotion Governor evaluates
these archives under the explicitly configured PAPER/champion policy.

## Local settings and credentials

Non-secret mode/product settings may be changed with:

```bash
uv run mastertrd config --mode PAPER --product SPOT
uv run mastertrd config --mode TESTNET --product SPOT
```

The app/CLI cannot configure LIVE.

Credentials stay in an OS secret store, protected environment injection, or a
user-owned environment file outside the repository. They are never persisted by
MasterTrd's local config.

### Binance TESTNET

```text
BINANCE_TESTNET_API_KEY
BINANCE_TESTNET_API_SECRET
BINANCE_TESTNET_ACCOUNT_ID
```

Missing TESTNET credentials fail closed. A real candidate-bound TESTNET smoke is an
external receipt and cannot be simulated into PASS.

### Binance LIVE

```text
BINANCE_LIVE_API_KEY
BINANCE_LIVE_API_SECRET
BINANCE_LIVE_ACCOUNT_ID
```

LIVE additionally requires both:

```bash
MASTERTRD_MODE=LIVE
LIVE_TRADING_ENABLED=true
```

Setting those variables is not sufficient by itself. The candidate must already be
LIVE-eligible through the Governor and the coherent TESTNET/risk/reconciliation/kill
evidence bundle must exist. First activation uses owner-selected minimal size and
strict caps.

## Accounts / Providers

The app reads `docs/MARKET_PROVIDER_MATRIX.md`'s corresponding code registry and shows
admission/blocker state. Binance is currently the only admitted execution provider.
Other Nautilus integrations stay `NOT_ADMITTED` until their provider-specific
execution, reconciliation, risk, credential isolation, PAPER/test, and Governor
requirements are implemented.

The UI reports whether required credential variable **names** are configured; it never
shows credential values.

## Emergency kill

The Trading tab has a persistent **EMERGENCY STOP**. Activating it creates a local stop
marker; `TradingService.preflight()` refuses worker start while it exists, and a
running `mastertrd trading` worker observes the same marker in its stop predicate.

For an unsafe or unknown state:

1. press **EMERGENCY STOP** or stop the supervised process;
2. verify the trading worker is no longer active;
3. inspect provider open orders/positions directly when credentials/capital are involved;
4. keep `LIVE_TRADING_ENABLED=false`;
5. reconcile local journal state with provider state;
6. diagnose/fix the cause and rerun PAPER/TESTNET evidence before any LIVE return.

The app can clear the marker only when the configured mode is not LIVE. LIVE recovery
requires deliberate external/operator review.

## Recovery

After a crash, reboot, network loss, or provider outage:

1. keep LIVE disabled;
2. verify the exact git/code identity and `uv lock --check`;
3. inspect `mastertrd status`, job logs, PAPER portfolio/session state, and data freshness;
4. reconcile expected orders/positions against the provider where applicable;
5. restart in PAPER or TESTNET;
6. verify risk, reconciliation, and completeness telemetry;
7. return to LIVE only after provider-specific evidence and Governor approval.

Portfolio replay is idempotent: the durable journal records market events and one shared
execution-state checkpoint before resumed risk is accepted.

## Linux

Use a normal user-owned checkout/virtual environment. A local supervisor may run:

```bash
uv run mastertrd trading
```

Do not use a temporary CI runner as the persistent execution host.

## Windows

From PowerShell:

```powershell
$env:MASTERTRD_MODE = "PAPER"
$env:LIVE_TRADING_ENABLED = "false"
uv run mastertrd app
uv run mastertrd trading
```

Task Scheduler or another local supervisor is optional; the safety variables are the
same as Linux.

## Logs and local data

Primary locations:

- `artifacts/local-jobs/` — receipts, logs, DuckDB, reports, data artifacts
- `artifacts/scheduler/` — scheduler state/logs/canary receipts
- `artifacts/trading/` — non-secret portfolio manifests and PAPER session state
- `~/.mastertrd/runtime.json` — safe local runtime settings only

Back up important DuckDB/Parquet/research artifacts separately. Never push private
trading state or secrets to GitHub.

## Rollback

Use a previously verified revision:

```bash
git checkout <verified-sha>
uv lock --check
uv sync --locked --all-extras
uv pip check
uv run pytest -q
```

Keep LIVE disabled during rollback. Do not roll back account/session state blindly;
provider reconciliation is authoritative before trading resumes.

## Secret rotation

1. Stop the affected trading worker.
2. Replace the key with withdrawal permission disabled and the narrowest supported
   permissions/IP restrictions.
3. Update only the protected local secret source.
4. Revoke the old key.
5. Run TESTNET/PAPER preflight and reconciliation before restoring the intended mode.

Vercel, PostHog, and Neon remain optional integrations only. MasterTrd continues to
operate locally when they are unavailable.
