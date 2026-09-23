# MasterTrd Thin Core / Full Lab / One Local App

Date: 2026-09-12
Status: IMPLEMENTED / CURRENT ARCHITECTURE

## Goal

MasterTrd becomes a local-first consumer trading product that keeps full research and trading capability while removing duplicated infrastructure.

Primary user flow:

Research -> Backtest -> PAPER -> LIVE

The user interacts with one local app. Heavy research runs in local worker processes. Trading runs in a separate local trading worker so backtests cannot freeze or crash execution.

## Product principles

- Keep capability; delete duplication.
- Prefer proven engines and provider integrations over custom wrappers.
- No mandatory SaaS service may sit in the critical path.
- No artificial MasterTrd cap on backtest count, strategy count, assets, or parameter sweeps; practical limits are local compute, data, storage, provider quotas, and cost.
- PAPER and LIVE use the same strategy/execution path; LIVE adds stricter gates, credentials, reconciliation, and risk controls.
- Experimental strategies remain researchable without becoming production-eligible.

## Runtime architecture

### 1. Local app

A single local web UI opened in the browser. The initial implementation uses Streamlit so it can call the existing Python core directly and avoid a separate frontend/backend product.

The app exposes only consumer concepts:

- Dashboard
- Strategies
- Backtest Lab
- Trading
- Accounts / Providers
- System Health

Advanced controls are hidden behind an advanced section rather than becoming separate operator workflows.

### 2. Research workers

Research jobs run as separate local processes. VectorBT handles high-volume screening and parameter grids. Optuna/pymoo handle search. NautilusTrader remains the authoritative execution-realistic validator.

A research failure must never stop the trading worker.

### 3. Trading worker

One persistent local trading worker owns PAPER/LIVE strategy execution. NautilusTrader owns order/execution semantics. MasterTrd owns strategy selection, portfolio/risk policy, promotion gates, and provider admission.

## Local storage and observability

DuckDB and Parquet remain the default durable local store for research results, market-data artifacts, experiment metadata, and summarized trading history.

Structured local logs replace mandatory PostHog. The UI reads local health/events/metrics from the same local data plane. External analytics may be added later as optional exporters only.

No Neon dependency is required. A future shared/team deployment may add Postgres as an optional adapter without changing core strategy or execution contracts.

## Cloud/service boundaries

- Vercel: not required.
- PostHog: not required.
- Neon: not required.
- GitHub: source control, backup, release artifacts, optional CI.
- GitHub-hosted Actions: never required for backtesting, monitoring, PAPER, or LIVE runtime.
- Local scheduler: replaces recurring GitHub cron for research/canaries/status jobs when running the consumer product.
- Provider APIs: used only for the market/data/execution capabilities they actually provide.

The product must keep working locally if all optional SaaS integrations are unavailable.

## Strategy model

Keep the strategy universe, but separate discovery from production.

Lifecycle:

Research -> Backtestable -> Validated -> PAPER -> Production Eligible

Experimental or provider-blocked recipes stay visible in research with explicit capability requirements. They do not add production runtime complexity until admitted.

Multiple strategies are first-class:

Account -> Portfolio -> Strategies

Strategies produce intents/targets. Portfolio/risk resolves exposure, conflicts, sizing, and account limits. NautilusTrader owns execution.

## Backtest Lab

The app can dispatch combinations across:

- many strategies
- many symbols/markets
- many timeframes
- date ranges and rolling/disjoint windows
- parameter grids and optimizer searches
- cost/slippage models
- seeds
- walk-forward and hidden/OOS tests
- robustness/neighbor tests
- portfolio combinations
- specialist engines when required by the strategy/data type

The UI presents queued/running/completed/failed jobs and comparative results. Failed and losing trials remain recorded; no cherry-picking.

## LIVE boundary

LIVE remains available as a product mode, but activation is provider-specific.

A provider may enter LIVE only after its data/execution path passes PAPER/testnet evidence, reconciliation, risk, credential isolation, restart/recovery, and kill-switch checks.

Required LIVE invariants stay fail-closed:

- explicit LIVE mode
- explicit live-enabled switch
- no withdrawal-capable keys
- pre-trade risk approval
- exposure/account limits
- reconciliation
- emergency kill
- restart/recovery evidence
- strategy/provider promotion approval

Simplification must not delete safety merely because a library already handles execution.

## Cleanup policy

Every existing module is classified KEEP, MERGE, REPLACE, or DELETE before removal.

Priority deletion/merging targets are duplicated PAPER status/session/evidence layers, overlapping runtime factories, cloud-only product plumbing, redundant acceptance/workflow wrappers, and dead provider paths.

Keep hard boundaries around strategy semantics, authoritative backtests, risk, provider admission, reconciliation, and recovery.

Do not rewrite proven third-party capabilities inside MasterTrd.

## Migration sequence

1. Inventory current modules/workflows into KEEP/MERGE/REPLACE/DELETE.
2. Introduce one local application entrypoint and one shared application service layer.
3. Move research execution behind local job workers and one unified result model.
4. Move PAPER/LIVE control behind one trading-worker interface using existing Nautilus paths.
5. Expose provider/account configuration through the app without copying provider internals.
6. Replace cloud-scheduled status/research jobs with local scheduling.
7. Consolidate local persistence around DuckDB/Parquet and structured logs.
8. Remove superseded wrappers only after parity tests prove the replacement.
9. Run historical/PAPER regression and failure/recovery tests.
10. Produce a consumer release that starts from one command/shortcut.

No big-bang rewrite. Each slice must preserve a working baseline.

## Completion contract

The repository will contain a durable progress ledger with:

- final product goal
- current implementation slice
- completed slices with commit/evidence
- next incomplete slice
- known blockers
- current PAPER/LIVE readiness

Every work session resumes from the first incomplete slice. A slice is not complete until its focused tests and required regression checks pass.

This ledger is the durable anti-stall mechanism; no claim is made that work continues while ChatGPT is not actively running.

## Acceptance criteria

Consumer-ready PAPER milestone:

- one local start command/shortcut opens the app
- strategy library and status are understandable without reading JSON or workflows
- batch backtests can run multiple strategies/assets/test methods locally
- research workers cannot block the trading worker
- results, losses, errors, and provenance persist locally
- multiple PAPER strategies can run concurrently through one portfolio/risk path
- dashboard shows positions, P&L, strategy state, risk state, jobs, and health
- emergency stop is visible and tested
- no Vercel/PostHog/Neon/GitHub-hosted Action dependency is required for runtime

Real-market milestone:

- at least one provider passes provider-specific LIVE admission
- PAPER and LIVE share strategy/execution semantics
- reconciliation, restart/recovery, credential isolation, and kill-switch tests pass
- LIVE remains explicitly locked until those receipts exist

## Non-goals

- rebuilding broker/exchange internals
- building a distributed cloud platform before local use requires it
- adding SaaS merely for convenience
- hiding failed research
- promoting strategies because the UI exists
- deleting safety controls to reduce line count

Success is measured by a simpler user flow and smaller ownership surface, not by an arbitrary LOC target.


## Opportunity Autopilot expansion (2026-09-23)

The local-first product now treats broad opportunity discovery as a first-class workflow rather than requiring the owner to manually assemble every backtest matrix.

### Simple and advanced control surfaces

The Streamlit app defaults to a Simple view centered on current opportunity-search status, the liquid-market universe, understandable research verdicts, and PAPER readiness/risk state. Advanced mode retains direct control over strategy selection, market product, symbols, timeframes, seeds, history windows, validation profiles, and matrix launches.

Research scores are explicitly presented as internal ranking signals, not expected profit or expected return.

### Liquid crypto universe

MasterTrd may discover a credential-free Binance universe from public exchange metadata and 24-hour quote volume. Liquidity ranking is a search-space filter only; it is never treated as alpha.

The initial admitted discovery products are Binance SPOT and Binance USD-M perpetual futures. Stablecoin bases and leveraged-token style products are excluded from the automatic liquid-market universe. Manual advanced selection remains available.

### Autonomous search

The local scheduler runs an Opportunity Autopilot cycle every six hours. Each cycle refreshes the liquid market universe when its cache is stale, rotates through the currently executable strategy catalog rather than repeatedly testing a fixed shortlist, launches only a bounded number of isolated research workers, uses multiple deterministic seeds, starts with a bounded history window for broad discovery, escalates promising shallow results to their full promotion-oriented history window, and preserves losing, blocked, and failed results.

The autopilot automatically prepares a shared SPOT PAPER portfolio only from candidates that actually reached the PAPER state and may start the persistent PAPER worker after a valid portfolio exists. The autonomous path never enables LIVE and never weakens the Promotion Governor.

### USD-M research boundary

Public checksum-verified Binance USD-M perpetual kline archives and exact Nautilus CryptoPerpetual metadata are admitted for BAR research and Nautilus validation.

USD-M research remains fail-closed at the forward-execution boundary: candidates are not automatically queued into PAPER until the dedicated USD-M PAPER streaming/execution bridge is admitted. Funding/basis, tick, L2, order-book, market-making, options, and cross-venue strategies still require their specialist data and validation paths.

This expansion increases opportunity coverage without pretending that NautilusTrader itself supplies profitable signals. Nautilus remains the authoritative execution engine; MasterTrd owns search, strategy semantics, validation, promotion, portfolio selection, and risk.
