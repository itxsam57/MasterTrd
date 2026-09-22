# MasterTrd

Local-first autonomous quantitative research, validation, PAPER/TESTNET, and controlled LIVE trading.

`MASTER_PLAN.md` is the product specification. The current local-first architecture is
`docs/superpowers/specs/2026-09-12-mastertrd-thin-core-local-first-design.md`.

## Safety defaults

- `MASTERTRD_MODE=PAPER`
- `LIVE_TRADING_ENABLED=false`
- Exchange keys must have **no withdrawal permission**
- Secrets and private account state never belong in git or research artifacts
- Only the Promotion Governor can advance strategy lifecycle state
- The app cannot enable LIVE and never submits orders directly

## Current status

**Implementation status: PROCESS_READY.** The code-owned V2 research, validation, execution, risk, recovery, specialist, and
promotion paths are implemented. The local-first consumer product is also implemented:
one Streamlit app, isolated research workers, a persistent `TradingService` worker,
shared multi-strategy PAPER execution through one Nautilus account/risk path, local
scheduling, result/health views, provider readiness, and a persistent emergency stop.

The current implementation regression is **727 passed, 0 failed**, with
`uv lock --check` and `uv pip check` clean. The release gate is exact-head acceptance;
`docs/THIN_CORE_PROGRESS.md` records the current closure evidence and
`docs/ACCEPTANCE_REPORT.md` remains the checked-in historical provenance snapshot.

This is still separate from LIVE eligibility. A real candidate-bound Binance TESTNET
receipt requires owner-provided TESTNET credentials/account identity and must pass the
risk/reconciliation/kill-switch evidence bundle. Until that external evidence exists, `testnet_smoke=BLOCKED_OWNER_INPUT`,
`LIVE_ELIGIBLE=false`, and real-money LIVE remains locked.

## Local start

Install the locked stack:

```bash
python -m pip install uv
uv lock --check
uv sync --locked --all-extras
uv pip check
```

Open the consumer app:

```bash
uv run mastertrd app
```

Run the persistent trading worker in a separate terminal/process:

```bash
uv run mastertrd trading
```

Useful commands:

```bash
uv run mastertrd status
uv run mastertrd strategies
uv run mastertrd jobs
uv run mastertrd scheduler
uv run mastertrd config --mode PAPER --product SPOT
```

## Research and Backtest Lab

The app's Backtest Lab can launch matrices across multiple executable recipes,
instruments, supported timeframes, seeds, and history horizons. Each matrix cell is an
isolated local worker and still runs the full MasterTrd validation path: screening,
optimization/evolution, Nautilus execution-realistic validation, robustness,
hidden/OOS, transfer testing, and required specialist gates. Failed and losing trials
remain visible.

Each job keeps its receipt, report, DuckDB memory, public-data artifacts, stdout, and
stderr under `artifacts/local-jobs/`.

## Shared PAPER portfolios

Research jobs export exact-provenance `PAPER` finalist manifests only after a candidate
reaches the PAPER lifecycle state. The Trading tab can combine at least two current-code
finalists into one shared PAPER portfolio. MasterTrd verifies code and `uv.lock`
identity before writing the portfolio configuration.

The persistent worker then runs the portfolio through:

- one Nautilus sandbox account/engine
- one shared `RiskRuntime`
- per-strategy StrategyGenome semantics and telemetry
- aggregate positions, exposure, equity, P&L, drawdown, and leverage
- one durable portfolio journal/reconciliation checkpoint
- real Binance public closed-bar data with per-timeframe completeness recovery
- flat-account evidence-window rotation into per-strategy forward PAPER archives

PAPER remains credential-free.

## Providers and LIVE

`docs/MARKET_PROVIDER_MATRIX.md` is the provider capability/admission registry.
Binance is the only currently admitted execution provider. Other integrations remain
visible but fail closed until their own data, execution, reconciliation, credential,
risk, PAPER/test, and Governor evidence is implemented.

Safe local mode/product settings are stored outside the repository at
`~/.mastertrd/runtime.json` by default. API keys and account IDs are **never** stored
there; they remain protected environment/OS-secret inputs.

LIVE still requires all of the following: explicit `MASTERTRD_MODE=LIVE`,
`LIVE_TRADING_ENABLED=true`, admitted provider credentials, a Governor-approved
LIVE-eligible candidate, coherent TESTNET evidence, reconciliation/recovery proof,
risk limits, and tested kill switches.

Operational details are in `docs/OPERATIONS.md`.
