# MasterTrd — Canonical Master Plan

**Status:** APPROVED / SOURCE OF TRUTH  
**Date:** 2026-08-29  
**Mission:** Build a zero-cost-first autonomous quantitative research, validation, paper/demo/testnet, and controlled live-trading platform. NautilusTrader is the sole authoritative execution engine. Strategies may be generated automatically, but no strategy can reach live eligibility without deterministic multi-stage validation and a hard risk governor.

## Non-negotiable principles

1. **Research before capital.** The platform must be useful with $0 trading capital.
2. **One execution engine.** NautilusTrader owns order lifecycle, positions, accounts, reconciliation, sandbox/demo/testnet/live execution.
3. **No secret in git.** Exchange API keys, private keys, seed phrases, account identifiers, balances, and sensitive live state never enter the public repository. GitHub Environments/Secrets or host environment variables are required.
4. **Live is disabled by default.** `LIVE_TRADING_ENABLED=false` is the default and there is no automatic fallback from paper/demo/testnet to live.
5. **No withdrawal permission.** Exchange keys used by the system must not have withdrawal permissions.
6. **Cumulative gates.** Every added dependency or subsystem must keep all previous tests green.
7. **No backtest-only promotion.** The Promotion Governor alone can promote strategies.
8. **Reproducibility.** Champion results record code SHA, dependency lock hash, dataset hash, genome hash, engine versions, seed, and parameter set.
9. **Public-repo safe.** Public artifacts use hashes/opaque IDs for experiment organization, but security depends on secret isolation and least privilege—not obscurity.
10. **Portable live node.** The same execution service must support local Linux/Windows development and an optional Oracle Always Free ARM64 deployment adapter.

## Trading coverage

MasterTrd must support strategy research and validation for:

- Scalping and order-book strategies
- Intraday/day trading
- Swing trading
- Position trading
- Trend following
- Momentum
- Breakouts
- Mean reversion
- Volatility strategies
- Grid strategies
- Market making
- Statistical arbitrage / pairs
- Cross-venue arbitrage
- Funding-rate and basis strategies
- Delta-neutral strategies
- Options research where the selected venue/account supports the product
- Portfolio/strategy rotation and risk allocation
- Experimental ML/factor/RL research without bypassing normal gates

## Core stack

### Authoritative execution
- `nautechsystems/nautilus_trader` — event engine, backtest, sandbox, demo/testnet/live execution, risk/execution adapters.

### Fast research and generation
- `polakowo/vectorbt` — high-throughput first-stage screening.
- `optuna/optuna` — constrained/multi-objective parameter optimization and pruning.
- `anyoptimization/pymoo` — structural/evolutionary strategy search.
- `TA-Lib/ta-lib-python` — research indicator implementations, with parity tests against execution calculations.

### Statistics, regimes, validation
- `statsmodels/statsmodels` — stationarity, regression, cointegration, statistical-arbitrage research.
- `bashtage/arch` — ARCH/GARCH, volatility forecasting, bootstrap/statistical tests.
- `deepcharles/ruptures` — historical structural-break/regime discovery.
- `online-ml/river` — online drift/anomaly monitoring.
- `skfolio/skfolio` — walk-forward/purged validation, portfolio/risk selection and stress analysis.
- `ranaroussi/quantstats` — independent performance tear sheets/metrics.
- `nkaz001/hftbacktest` — specialist queue/latency/order-book validation for scalping/HFT/market-making candidates only; never the authoritative live executor.

### Data and memory
- `duckdb/duckdb` — query/research memory.
- Parquet — canonical historical/research data format.
- `binance/binance-public-data` — initial no-key crypto historical data.
- `ccxt/ccxt` — data fallback only, not execution.

### Optional/future research plugins
- `blue-yonder/tsfresh` — automated feature extraction.
- `microsoft/qlib` — ML/factor laboratory.
- `microsoft/RD-Agent` — optional LLM research proposal source; system must remain autonomous without it.
- FinRL family — optional RL research only; normal validation still applies.
- Hummingbot — reference source for market-making/arbitrage ideas only; not a second runtime engine.

## Universal contracts

### MarketDataContract
All research/execution adapters normalize to a canonical representation with at minimum:

`timestamp, venue, instrument, timeframe, open, high, low, close, volume`

Optional fields include:

`bid, ask, trade_count, funding_rate, open_interest, liquidations, book_depth, trades`

### StrategyGenome
Strategies are represented as data rather than thousands of hand-written files. The genome includes:

- opaque strategy ID/hash
- strategy family/style
- universe and venue constraints
- timeframe/data requirements
- entry expression tree
- exit expression tree
- filters/regime constraints
- stop/take-profit/trailing rules
- position-sizing policy
- risk budget
- long/short capability
- execution requirements (bar/tick/L2/L3)

The genome is compiled into fast-screening and Nautilus execution representations.

### ResultContract
Every evaluation produces the same comparable result shape including:

- strategy/genome/dataset/code hashes
- engine and version
- returns, Sharpe, Sortino, drawdown, profit factor, expectancy
- trade count, turnover, fees, slippage
- regime scores
- walk-forward/purged-CV/hidden/stress/parameter-stability/cost-stability scores
- status and failure reason

## Research brain

Autonomous cycle:

1. Update/verify market data.
2. Load prior research memory.
3. Discover historical/current regimes.
4. Generate new genomes and mutations.
5. Use VectorBT for cheap broad screening.
6. Use Optuna to tune numerical parameters under risk constraints.
7. Use pymoo for structural multi-objective evolution.
8. Validate survivors in NautilusTrader.
9. Run specialist tests when required: statsmodels/arch/skfolio/QuantStats/hftbacktest.
10. Run hidden/out-of-sample, walk-forward, purged CV, parameter perturbation, cost/slippage/latency and Monte Carlo stress.
11. Store failures and successes in research memory.
12. Queue only qualified candidates for forward paper/demo tests.
13. Re-rank Champion/Challenger pools.

## Promotion state machine

`IDEA -> SCREENED -> BACKTESTED -> ROBUST -> HIDDEN_PASS -> PAPER -> CHALLENGER -> CHAMPION -> LIVE_ELIGIBLE`

Failure produces `QUARANTINED` or `REJECTED` with a machine-readable reason.

No library, optimizer, ML model, or strategy can write a later state directly. Only the Promotion Governor can transition state after verifying required evidence.

## Validation policy

At minimum, strategies face:

- training/validation/hidden partitions
- out-of-sample testing
- walk-forward testing
- purged/combinatorial purged CV where applicable
- fee and slippage stress
- parameter-neighborhood perturbation
- regime-by-regime testing
- Monte Carlo/trade-order stress
- transfer testing across appropriate symbols/time periods
- forward paper/demo testing

Scalping/HFT/order-book/market-making strategies additionally require queue, latency and order-book validation. Candle-only evidence can never promote such a candidate to live eligibility.

## Risk governor

The risk system is independent from strategy logic and must support hard limits for:

- per-order size
- per-symbol exposure
- portfolio exposure
- leverage
- order rate
- daily loss
- drawdown
- correlated exposure
- stale/missing data
- abnormal spreads/volatility
- reconciliation mismatch
- duplicate orders
- exchange/API degradation

Kill switches exist at strategy, symbol, venue, portfolio and system level.

## Runtime modes

One codebase supports:

- `RESEARCH`
- `BACKTEST`
- `PAPER`
- `DEMO`
- `TESTNET`
- `LIVE`

Live mode additionally requires `LIVE_TRADING_ENABLED=true` plus an explicit live venue environment and valid live credentials.

## Execution targets

### GitHub Actions
Use public standard runners for research, testing, optimization, validation, reports and coarse paper-state jobs. GitHub scheduled jobs are not treated as a low-latency execution server.

### Local execution node
A lightweight local node may run market streams, signals, orders, reconciliation and risk controls. Heavy research remains off the low-powered PC.

### Oracle adapter
Build and test but leave disabled by default. Target Linux ARM64/Ampere A1 with bootstrap, systemd, health check, restart/recovery, log rotation, environment loader and deployment workflow. `ORACLE_ENABLED=false` until host details are supplied.

## Secret and public-repository policy

Never commit:

- `.env`
- API keys/secrets
- SSH private keys
- seed phrases/passwords
- raw account IDs
- balances/current private positions
- sensitive API payloads
- private live state

Public fixtures must be synthetic/redacted. CI runs secret scanning and dependency/security checks.

## Repository target structure

- `src/mastertrd/contracts/` — canonical contracts
- `src/mastertrd/genome/` — strategy language/compiler interfaces
- `src/mastertrd/governor/` — promotion and risk policy
- `src/mastertrd/research/` — screening/optimization/evolution/statistics/regimes
- `src/mastertrd/validation/` — robustness and specialist gates
- `src/mastertrd/execution/` — Nautilus adapters and modes
- `src/mastertrd/storage/` — DuckDB/Parquet persistence
- `src/mastertrd/adapters/` — data/venue/GitHub/Oracle/local integrations
- `tests/` — unit/integration/contract/regression tests
- `.github/workflows/` — cumulative CI/research/security workflows
- `docs/` — architecture, operations and implementation plans

## Dependency admission gate

A dependency is admitted only after:

`INSTALL -> IMPORT -> UNIT -> SMOKE -> DATA CONTRACT -> RESULT CONTRACT -> DETERMINISM -> REGRESSION`

Failures block stacking.

## Definition of done

MasterTrd is not complete because code compiles. Completion requires evidence for:

- clean public clone/install
- pinned dependency lock
- unit/contract/integration/regression suites
- historical-data import and integrity verification
- strategy generation and deterministic genome hashing
- VectorBT screen
- Optuna optimization
- pymoo evolution
- Nautilus backtest
- validation pipeline and hidden gate
- specialist HFT gate
- research memory/reproducibility
- paper-state persistence/recovery
- supported venue demo/testnet smoke tests when credentials are available
- reconciliation and kill switch tests
- secret/public-repo audit
- ARM64/Oracle deployment artifact
- cumulative green CI

Live execution may be code-complete without risking material money; first live activation must use an owner-selected minimal size, one strategy/instrument, strict caps and automatic kill switches.

## Owner inputs still required later

- Exchange names/accounts to connect.
- API credentials entered directly into GitHub/host secrets, never chat or git.
- Oracle hostname/user once Always Free access exists; SSH private material goes into secrets, never chat or repository.

This file is the canonical MasterTrd product specification. Implementation changes may strengthen it, but may not silently weaken or remove these requirements.