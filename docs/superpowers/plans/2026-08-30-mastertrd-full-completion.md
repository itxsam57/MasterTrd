# MasterTrd Full Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved `MASTER_PLAN.md` from the current safe foundation into an end-to-end autonomous research, validation, paper/demo/testnet, and guarded live-execution platform without weakening any safety gate.

**Architecture:** Keep NautilusTrader as the only authoritative execution engine. Split the remaining work into deterministic data ingestion, family-aware strategy compilation, broad research/optimization, autonomous orchestration, risk/execution wiring, specialist validation, forward paper/demo/testnet execution, and deployment/acceptance gates. Every subsystem produces machine-verifiable evidence consumed by the Promotion Governor; LIVE remains fail-closed.

**Tech Stack:** Python 3.13, pytest, NautilusTrader, VectorBT, Optuna, pymoo, TA-Lib, statsmodels, arch, ruptures, River, skfolio, QuantStats, hftbacktest, DuckDB, Parquet, ccxt data fallback, GitHub Actions.

**Spec:** `MASTER_PLAN.md`

## Global Constraints

- NautilusTrader is the sole authoritative execution engine.
- `LIVE_TRADING_ENABLED=false` by default.
- No automatic fallback from paper/demo/testnet to live.
- Exchange credentials and private live/account state never enter git.
- Exchange keys used by the system must not have withdrawal permissions.
- Only the Promotion Governor can advance strategy lifecycle state.
- Every champion result records code SHA, dependency lock hash, dataset hash, genome hash, engine versions, seed, and parameter set.
- Candle-only evidence can never promote scalping/HFT/order-book/market-making candidates to live eligibility.
- GitHub Actions may run research, validation, reports, and coarse paper-state jobs, but never acts as a low-latency live execution server.
- Oracle deployment remains disabled unless `ORACLE_ENABLED=true` and owner-supplied host secrets exist.
- Existing `asset_transfer` evidence remains mandatory for robust promotion; it must not be removed or replaced with a weaker synthetic marker.

---

### Task 1: Establish exact-head completion acceptance gate

**Files:**
- Create: `src/mastertrd/acceptance.py`
- Create: `tests/test_acceptance.py`
- Create: `.github/workflows/acceptance.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: `AcceptanceCheck(name: str, passed: bool, detail: str)` and `run_static_acceptance(repo_root: Path) -> tuple[AcceptanceCheck, ...]`.
- Later tasks append dynamic evidence to the same acceptance report schema.

- [ ] **Step 1: Write the failing acceptance tests**

```python
from pathlib import Path
from mastertrd.acceptance import run_static_acceptance


def test_static_acceptance_requires_lock_and_master_plan(tmp_path: Path):
    checks = run_static_acceptance(tmp_path)
    failed = {c.name for c in checks if not c.passed}
    assert "master_plan" in failed
    assert "dependency_lock" in failed
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `uv run pytest tests/test_acceptance.py -v`
Expected: FAIL because `mastertrd.acceptance` does not exist.

- [ ] **Step 3: Implement static acceptance checks and workflow**

```python
@dataclass(frozen=True, slots=True)
class AcceptanceCheck:
    name: str
    passed: bool
    detail: str


def run_static_acceptance(repo_root: Path) -> tuple[AcceptanceCheck, ...]:
    required = {
        "master_plan": repo_root / "MASTER_PLAN.md",
        "dependency_lock": repo_root / "uv.lock",
    }
    return tuple(
        AcceptanceCheck(name, path.exists(), str(path))
        for name, path in required.items()
    )
```

Add an `acceptance.yml` workflow that installs from `uv.lock`, runs all unit/integration suites, then runs `python -m mastertrd.acceptance` and uploads the generated acceptance JSON artifact.

- [ ] **Step 4: Run acceptance unit tests and existing core tests**

Run: `uv run pytest tests/test_acceptance.py tests/test_contracts.py tests/test_runtime.py tests/test_governor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/acceptance.py tests/test_acceptance.py .github/workflows/acceptance.yml README.md
git commit -m "test: establish completion acceptance gate"
```

---

### Task 2: Complete deterministic historical-data pipeline and Parquet store

**Files:**
- Modify: `src/mastertrd/data/binance_public.py`
- Create: `src/mastertrd/data/archive.py`
- Create: `src/mastertrd/data/parquet_store.py`
- Create: `src/mastertrd/data/ccxt_fallback.py`
- Create: `tests/test_data_archive.py`
- Create: `tests/test_parquet_store.py`
- Create: `tests/test_ccxt_fallback.py`

**Interfaces:**
- Produces: `DatasetManifest`, `download_binance_month(...) -> DatasetManifest`, `verify_archive(...) -> DatasetManifest`, `write_market_bars(...) -> DatasetManifest`, `read_market_bars(...) -> tuple[MarketBar, ...]`, and `fetch_ohlcv_fallback(...) -> tuple[MarketBar, ...]`.
- `DatasetManifest.dataset_hash` is the canonical dataset identity consumed by research and validation.

- [ ] **Step 1: Write checksum and round-trip tests**

```python
def test_archive_rejects_checksum_mismatch(tmp_path):
    archive = tmp_path / "bars.zip"
    archive.write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        verify_archive(archive, expected_sha256="0" * 64)


def test_parquet_roundtrip_preserves_market_bar(tmp_path, sample_bar):
    manifest = write_market_bars(tmp_path / "bars.parquet", [sample_bar])
    bars = read_market_bars(manifest.path)
    assert bars == (sample_bar,)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_data_archive.py tests/test_parquet_store.py tests/test_ccxt_fallback.py -v`
Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement verified ingestion**

`DatasetManifest` must contain: `source`, `venue`, `instrument`, `timeframe`, `first_timestamp`, `last_timestamp`, `row_count`, `file_sha256`, `dataset_hash`, and `path`. ZIP extraction must reject path traversal, malformed rows, duplicate/non-monotonic timestamps, and checksum mismatch. Parquet writes must be atomic (`.tmp` then `replace`). `ccxt_fallback` is data-only and must reject any exchange object exposing an attempted order call through this adapter.

- [ ] **Step 4: Run data tests plus existing Binance parser tests**

Run: `uv run pytest tests/test_binance_data.py tests/test_data_archive.py tests/test_parquet_store.py tests/test_ccxt_fallback.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/data tests/test_data_archive.py tests/test_parquet_store.py tests/test_ccxt_fallback.py
git commit -m "feat: complete verified market data pipeline"
```

---

### Task 3: Replace the EMA-only compiler with family-aware executable strategies

**Files:**
- Modify: `src/mastertrd/nautilus_strategy.py`
- Create: `src/mastertrd/execution_signals.py`
- Create: `src/mastertrd/nautilus_bar_strategy.py`
- Create: `src/mastertrd/nautilus_multileg_strategy.py`
- Create: `src/mastertrd/nautilus_options_strategy.py`
- Modify: `tests/integration/test_nautilus_strategy_compiler.py`
- Create: `tests/integration/test_nautilus_family_compilers.py`
- Create: `tests/test_execution_signal_parity.py`

**Interfaces:**
- Produces: `compile_genome_to_nautilus(genome, *, instrument, trade_size_override=None, instrument_map=None)`.
- Produces deterministic pure signal evaluators: `evaluate_bar_signal(genome, bars) -> SignalDecision`, `evaluate_multileg_signal(genome, series_by_instrument) -> SignalDecision`.
- Bar families supported here: `trend`, `momentum`, `breakout`, `mean_reversion`, `volatility`, `swing`, `position`.
- Multi-leg families supported here: `stat_arb`, `funding_basis`, `delta_neutral`, `portfolio`.
- Options family uses a defined-risk research/execution adapter and remains unavailable on venues lacking required options metadata.
- `scalping`, `grid`, `market_making`, `order_book`, and `cross_venue_arb` route to the specialist HFT compiler and may not silently fall back to candle execution.

- [ ] **Step 1: Expand compiler tests to every family**

```python
@pytest.mark.parametrize("family", [
    "trend", "momentum", "breakout", "mean_reversion", "volatility",
    "swing", "position", "stat_arb", "funding_basis", "delta_neutral",
    "portfolio", "options",
])
def test_supported_family_compiles(family, generated_genome, instrument_fixture):
    strategy = compile_genome_to_nautilus(
        generated_genome(family),
        instrument=instrument_fixture,
        trade_size_override="0.001",
    )
    assert strategy is not None
```

Add tests asserting specialist families raise `SpecialistPathRequired` rather than generic `ValueError`.

- [ ] **Step 2: Run compiler tests and confirm RED on non-EMA families**

Run: `uv run pytest tests/integration/test_nautilus_strategy_compiler.py tests/integration/test_nautilus_family_compilers.py -v`
Expected: FAIL for all non-EMA families.

- [ ] **Step 3: Implement pure signals and custom Nautilus strategies**

Implement the generated rules already emitted by `research/generator.py`: EMA cross, RSI momentum, Donchian breakout, z-score reversion, volatility breakout, pullback trend, long-horizon trend, cointegration spread, funding basis, hedged basis, volatility/options signal, and strategy rotation. Keep indicator calculations in `execution_signals.py`; Nautilus classes only handle subscriptions, order intents, and event lifecycle.

- [ ] **Step 4: Add TA-Lib/execution parity tests**

For EMA, RSI, ATR, Donchian extrema, and z-score, compare the pure execution calculation to the research implementation over deterministic fixtures with a tolerance of `1e-9` where floating-point representation permits.

Run: `uv run pytest tests/test_execution_signal_parity.py tests/integration/test_nautilus_family_compilers.py tests/integration/test_nautilus_strategy_activity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/nautilus_strategy.py src/mastertrd/execution_signals.py src/mastertrd/nautilus_bar_strategy.py src/mastertrd/nautilus_multileg_strategy.py src/mastertrd/nautilus_options_strategy.py tests/integration tests/test_execution_signal_parity.py
git commit -m "feat: compile generated strategy families to Nautilus"
```

---

### Task 4: Generalize VectorBT screening and constrained optimization

**Files:**
- Modify: `src/mastertrd/research/screen.py`
- Modify: `src/mastertrd/research/optimize.py`
- Modify: `src/mastertrd/research/advanced.py`
- Create: `src/mastertrd/research/evolve.py`
- Create: `tests/test_research_screen.py`
- Create: `tests/test_research_optimize.py`
- Create: `tests/test_research_evolve.py`

**Interfaces:**
- Produces: `screen_genome(genome, bars_by_instrument, *, fees, slippage) -> EvaluationResult`.
- Produces: `optimize_genome(base_genome, parameter_space, objective, *, trials, seed) -> GenomeOptimizationResult`.
- Produces: `evolve_genomes(seed_genomes, objective, *, generations, population, seed) -> tuple[StrategyGenome, ...]`.
- Structural evolution may mutate entry/exit/filter parameters only within the registered family schema; it may not mutate lifecycle state or bypass data requirements.

- [ ] **Step 1: Write family-screen and multi-parameter optimization tests**

```python
def test_screen_result_keeps_original_genome_hash(genome, bars):
    result = screen_genome(genome, {genome.instruments[0]: bars}, fees=0.001, slippage=0.0005)
    assert result.genome_hash == genome.genome_hash


def test_optimizer_respects_parameter_bounds(base_genome):
    result = optimize_genome(
        base_genome,
        {"entry.fast": (5, 20), "entry.slow": (30, 100)},
        objective=lambda g: -abs(g.entry["fast"] - 10),
        trials=16,
        seed=7,
    )
    assert 5 <= result.best_genome.entry["fast"] <= 20
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_research_screen.py tests/test_research_optimize.py tests/test_research_evolve.py -v`
Expected: FAIL because generalized APIs do not exist.

- [ ] **Step 3: Implement genome-aware screening, Optuna, and pymoo evolution**

Screening must use the same pure signal functions as Task 3 for bar families so research/execution semantics do not diverge. Optimization must support int/float/categorical parameter definitions and multi-objective score vectors with hard constraint rejection. Evolution must return valid, hash-stable `StrategyGenome` objects only.

- [ ] **Step 4: Run research stack regression**

Run: `uv run pytest tests/test_research_screen.py tests/test_research_optimize.py tests/test_research_evolve.py tests/integration/test_research_stack.py tests/integration/test_advanced_research.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/research tests/test_research_screen.py tests/test_research_optimize.py tests/test_research_evolve.py
git commit -m "feat: generalize research screening and evolution"
```

---

### Task 5: Implement regimes, statistics, volatility, portfolio stress, and independent reporting

**Files:**
- Create: `src/mastertrd/research/regimes.py`
- Create: `src/mastertrd/research/statistics.py`
- Create: `src/mastertrd/research/volatility.py`
- Create: `src/mastertrd/research/portfolio.py`
- Create: `src/mastertrd/research/reporting.py`
- Create: `tests/test_regimes.py`
- Create: `tests/test_statistics.py`
- Create: `tests/test_volatility.py`
- Create: `tests/test_portfolio_research.py`
- Create: `tests/test_reporting.py`

**Interfaces:**
- `discover_regimes(returns, *, min_size, penalty) -> RegimeMap` using ruptures.
- `cointegration_evidence(left, right, *, max_pvalue) -> StatisticalEvidence` using statsmodels.
- `forecast_volatility(returns, *, horizon) -> VolatilityForecast` using arch.
- `portfolio_stress(returns_frame, *, train_size, test_size, purged_size) -> PortfolioStressEvidence` using skfolio.
- `build_independent_report(returns, *, periods) -> IndependentReport` using QuantStats.

- [ ] **Step 1: Write deterministic specialist tests**

Use seeded synthetic stationary/non-stationary pairs, volatility-clustered returns, and a fixed multi-asset returns frame. Assert evidence is finite, hashable, and contains the input dataset hash.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_regimes.py tests/test_statistics.py tests/test_volatility.py tests/test_portfolio_research.py tests/test_reporting.py -v`
Expected: FAIL because specialist modules do not exist.

- [ ] **Step 3: Implement specialist modules with typed evidence**

Each module must validate finite input, reject too-short samples, return machine-readable evidence, and never mutate promotion state.

- [ ] **Step 4: Run specialist and advanced-research suites**

Run: `uv run pytest tests/test_regimes.py tests/test_statistics.py tests/test_volatility.py tests/test_portfolio_research.py tests/test_reporting.py tests/integration/test_advanced_research.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/research tests/test_regimes.py tests/test_statistics.py tests/test_volatility.py tests/test_portfolio_research.py tests/test_reporting.py
git commit -m "feat: add statistical and regime specialist gates"
```

---

### Task 6: Build the autonomous research brain and champion/challenger scheduler

**Files:**
- Create: `src/mastertrd/research_brain.py`
- Modify: `src/mastertrd/research_cycle.py`
- Modify: `src/mastertrd/champion.py`
- Modify: `src/mastertrd/memory_duckdb.py`
- Create: `tests/test_research_brain.py`
- Create: `tests/integration/test_autonomous_research_cycle.py`

**Interfaces:**
- `ResearchBrainConfig` defines family set, instruments, seed range, screening thresholds, optimization budget, evolution budget, validation budget, and paper-queue cap.
- `run_research_brain(config, dataset, memory, *, code_hash, lock_hash) -> ResearchBrainReport` executes the approved 13-stage cycle.
- The brain may request governor transitions but cannot write strategy states directly.

- [ ] **Step 1: Write a deterministic end-to-end orchestration test**

```python
def test_research_brain_stores_failures_and_queues_only_qualified(...):
    report = run_research_brain(config, dataset, memory, code_hash="c" * 64, lock_hash="l" * 64)
    assert report.generated > 0
    assert report.stored == report.generated
    assert all(item.state in {"REJECTED", "QUARANTINED", "PAPER"} for item in report.finalists)
```

- [ ] **Step 2: Run orchestration tests and confirm RED**

Run: `uv run pytest tests/test_research_brain.py tests/integration/test_autonomous_research_cycle.py -v`
Expected: FAIL because `research_brain` does not exist.

- [ ] **Step 3: Implement the 13-stage cycle exactly from `MASTER_PLAN.md`**

Order: verified data -> load memory -> regime discovery -> generation/mutation -> VectorBT screen -> Optuna tune -> pymoo evolution -> Nautilus validation -> specialist tests -> hidden/robustness stress -> store all outcomes -> queue qualified paper candidates -> re-rank champion/challenger. Persist stage receipts so interrupted jobs resume idempotently from the last completed stage.

- [ ] **Step 4: Run research, hidden, robustness, and memory integration suites**

Run: `uv run pytest tests/test_research_brain.py tests/integration/test_autonomous_research_cycle.py tests/integration/test_generated_backtest_cycle.py tests/integration/test_generated_robustness_cycle.py tests/integration/test_generated_hidden_cycle.py tests/integration/test_duckdb_memory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/research_brain.py src/mastertrd/research_cycle.py src/mastertrd/champion.py src/mastertrd/memory_duckdb.py tests/test_research_brain.py tests/integration/test_autonomous_research_cycle.py
git commit -m "feat: wire autonomous research brain"
```

---

### Task 7: Expand the independent risk governor and wire it into order intent

**Files:**
- Modify: `src/mastertrd/risk.py`
- Create: `src/mastertrd/risk_runtime.py`
- Modify: `src/mastertrd/nautilus_bar_strategy.py`
- Modify: `src/mastertrd/nautilus_multileg_strategy.py`
- Modify: `src/mastertrd/nautilus_options_strategy.py`
- Create: `tests/test_risk_runtime.py`
- Modify: `tests/test_risk.py`
- Create: `tests/integration/test_execution_risk_hook.py`

**Interfaces:**
- Extend `RiskLimits` with leverage, correlated exposure, max spread, max volatility, duplicate-order window, and API-health thresholds.
- Extend `RiskSnapshot` with leverage, correlated exposure, spread, realized volatility, duplicate-order flag, venue/API health, and reconciliation age.
- `RiskRuntime.check_order(intent, snapshot) -> RiskDecision` is mandatory before any Nautilus order submission.
- `RiskRuntime.kill(scope, reason)` supports strategy, symbol, venue, portfolio, and system scopes.

- [ ] **Step 1: Write missing-control and execution-hook tests**

Assert abnormal spread blocks orders, stale reconciliation kills the system, duplicate orders are blocked, API degradation blocks new risk, and no strategy can submit an order without a recorded `ALLOW` decision.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_risk.py tests/test_risk_runtime.py tests/integration/test_execution_risk_hook.py -v`
Expected: FAIL because the extra controls/runtime hook do not exist.

- [ ] **Step 3: Implement expanded risk policy and mandatory hook**

Keep `evaluate_risk` pure. `RiskRuntime` owns rolling order fingerprints, API health, correlation snapshots, and kill state. Order strategies receive a `RiskRuntime` dependency and must abort submission on any result other than `ALLOW`.

- [ ] **Step 4: Run risk, strategy, and live-readiness regressions**

Run: `uv run pytest tests/test_risk.py tests/test_risk_runtime.py tests/integration/test_execution_risk_hook.py tests/integration/test_nautilus_strategy_activity.py tests/test_live_readiness.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/risk.py src/mastertrd/risk_runtime.py src/mastertrd/nautilus_*strategy.py tests/test_risk.py tests/test_risk_runtime.py tests/integration/test_execution_risk_hook.py
git commit -m "feat: enforce risk governor on execution path"
```

---

### Task 8: Complete persistent paper/demo/testnet execution, reconciliation, and recovery

**Files:**
- Modify: `src/mastertrd/live_node.py`
- Modify: `src/mastertrd/nautilus_paper.py`
- Modify: `src/mastertrd/paper_forward.py`
- Create: `src/mastertrd/streaming.py`
- Create: `src/mastertrd/reconciliation.py`
- Create: `src/mastertrd/execution_runtime.py`
- Create: `tests/test_streaming.py`
- Create: `tests/test_reconciliation.py`
- Create: `tests/integration/test_paper_live_feed.py`
- Create: `tests/integration/test_runtime_recovery.py`

**Interfaces:**
- `MarketStream` normalizes live bars/ticks to canonical contracts.
- `Reconciler.reconcile(engine_state, venue_state) -> ReconciliationResult` detects position/order/account mismatch.
- `ExecutionRuntime.run()` drives stream -> signals -> risk -> Nautilus order lifecycle -> event journal -> reconciliation.
- Restart recovery reloads the paper/session journal and replays idempotently before accepting new orders.

- [ ] **Step 1: Write stream/reconciliation/restart tests**

Use deterministic fake streams and fake venue snapshots. Assert disconnect/reconnect does not duplicate orders, restart restores journal identity, and reconciliation mismatch triggers the system kill switch.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_streaming.py tests/test_reconciliation.py tests/integration/test_paper_live_feed.py tests/integration/test_runtime_recovery.py -v`
Expected: FAIL because runtime plumbing is missing.

- [ ] **Step 3: Implement persistent runtime**

`live_node.py` becomes a thin process wrapper around `ExecutionRuntime`; heartbeat remains observability only. PAPER uses real public market data with simulated fills. DEMO/TESTNET use exchange sandbox credentials and Nautilus adapters. LIVE uses the same runtime but remains blocked by live-readiness evidence and explicit environment flags.

- [ ] **Step 4: Run paper ledger/session/Nautilus paper regressions**

Run: `uv run pytest tests/test_paper_ledger.py tests/test_paper_session_journal.py tests/test_paper_session_persistence.py tests/test_paper_session_safety.py tests/integration/test_nautilus_paper_sandbox.py tests/integration/test_paper_live_feed.py tests/integration/test_runtime_recovery.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/live_node.py src/mastertrd/nautilus_paper.py src/mastertrd/paper_forward.py src/mastertrd/streaming.py src/mastertrd/reconciliation.py src/mastertrd/execution_runtime.py tests/test_streaming.py tests/test_reconciliation.py tests/integration/test_paper_live_feed.py tests/integration/test_runtime_recovery.py
git commit -m "feat: complete persistent paper and exchange runtime"
```

---

### Task 9: Add real order-book/L2 specialist path for HFT families

**Files:**
- Modify: `src/mastertrd/research/hft_specialist.py`
- Modify: `src/mastertrd/hft_validation.py`
- Create: `src/mastertrd/data/orderbook.py`
- Create: `src/mastertrd/hft_strategy.py`
- Create: `tests/test_orderbook_data.py`
- Create: `tests/integration/test_real_l2_hft_gate.py`

**Interfaces:**
- `OrderBookDataset` requires bid/ask levels, event timestamps, sequence integrity, and dataset hash.
- `validate_hft_candidate(genome, dataset, *, latency_profile, queue_model) -> ValidationEvidence` must reject synthetic-only evidence for promotion beyond robustness.
- Supported specialist families: scalping, grid, market_making, order_book, cross_venue_arb.

- [ ] **Step 1: Write L2-integrity and synthetic-only rejection tests**

Assert missing sequence numbers, crossed books, negative size, or candle-only datasets fail closed. Assert synthetic stress remains useful but is marked `supporting_only=True`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_orderbook_data.py tests/integration/test_real_l2_hft_gate.py -v`
Expected: FAIL because real L2 path does not exist.

- [ ] **Step 3: Implement order-book contract and hftbacktest adapter**

Normalize historical L2 events, enforce sequence/clock integrity, run queue/latency/spread/inventory stress, and produce evidence linked to the exact L2 dataset hash.

- [ ] **Step 4: Run existing and new HFT suites**

Run: `uv run pytest tests/test_hft_validation.py tests/integration/test_hftbacktest_engine_probe.py tests/integration/test_hftbacktest_stress_suite.py tests/test_orderbook_data.py tests/integration/test_real_l2_hft_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/research/hft_specialist.py src/mastertrd/hft_validation.py src/mastertrd/data/orderbook.py src/mastertrd/hft_strategy.py tests/test_orderbook_data.py tests/integration/test_real_l2_hft_gate.py
git commit -m "feat: require real L2 evidence for HFT promotion"
```

---

### Task 10: Produce live-eligibility evidence: risk review, reconciliation, kill switch, and testnet smoke

**Files:**
- Modify: `src/mastertrd/live_readiness.py`
- Create: `src/mastertrd/live_evidence.py`
- Create: `tests/test_live_evidence.py`
- Modify: `tests/test_live_readiness.py`
- Create: `tests/integration/test_kill_switch_evidence.py`
- Create: `tests/integration/test_reconciliation_evidence.py`

**Interfaces:**
- `run_risk_review(...) -> ValidationEvidence`
- `run_reconciliation_probe(...) -> ValidationEvidence`
- `run_kill_switch_probe(...) -> ValidationEvidence`
- `run_testnet_smoke(...) -> ValidationEvidence`
- Existing `asset_transfer` evidence remains a separate required gate.

- [ ] **Step 1: Write fail-closed evidence tests**

Evidence must fail if any probe was skipped, simulated without the required runtime mode, produced against a different code/genome/dataset hash, or cannot prove that post-kill order submission was blocked.

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_live_evidence.py tests/integration/test_kill_switch_evidence.py tests/integration/test_reconciliation_evidence.py -v`
Expected: FAIL because evidence producers do not exist.

- [ ] **Step 3: Implement evidence producers and governor requirements**

Wire required evidence names into live-readiness checks. Testnet smoke places only venue-minimum notional sandbox/test orders and is skipped with a machine-readable `credentials_unavailable` result when secrets are absent; it must never silently substitute LIVE.

- [ ] **Step 4: Run live-readiness and promotion regression suites**

Run: `uv run pytest tests/test_live_evidence.py tests/test_live_readiness.py tests/test_governor.py tests/integration/test_kill_switch_evidence.py tests/integration/test_reconciliation_evidence.py tests/test_asset_transfer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/live_readiness.py src/mastertrd/live_evidence.py tests/test_live_evidence.py tests/test_live_readiness.py tests/integration/test_kill_switch_evidence.py tests/integration/test_reconciliation_evidence.py
git commit -m "feat: produce complete live eligibility evidence"
```

---

### Task 11: Add scheduled autonomous research and credential-gated demo/testnet workflows

**Files:**
- Create: `.github/workflows/autonomous-research.yml`
- Create: `.github/workflows/testnet-smoke.yml`
- Modify: `.github/workflows/research-stack.yml`
- Modify: `.github/workflows/execution-stack.yml`
- Create: `tests/test_workflow_policy.py`

**Interfaces:**
- Research workflow runs `ResearchBrain` on verified public data and uploads only public-safe reports/artifacts.
- Testnet workflow requires GitHub Environment `testnet`, has no LIVE variables, and refuses to run if any withdrawal-capable credential marker is present.

- [ ] **Step 1: Write workflow-policy tests**

Parse YAML and assert scheduled research has no live secrets, testnet workflow contains `MASTERTRD_MODE=TESTNET`, LIVE is absent, and no workflow grants broad write permissions by default.

- [ ] **Step 2: Run policy tests and confirm RED**

Run: `uv run pytest tests/test_workflow_policy.py -v`
Expected: FAIL because workflows do not exist.

- [ ] **Step 3: Implement workflows**

Use pinned Python/uv setup, dependency lock verification, artifact retention, concurrency cancellation for stale research runs, and environment-scoped testnet secrets. Do not schedule LIVE.

- [ ] **Step 4: Run workflow policy plus security tests**

Run: `uv run pytest tests/test_workflow_policy.py tests/test_credentials.py tests/test_dependencies.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows tests/test_workflow_policy.py
git commit -m "ci: add autonomous research and testnet gates"
```

---

### Task 12: Complete Oracle/local deployment artifacts without using Vercel as the live runtime

**Files:**
- Modify: `src/mastertrd/oracle.py`
- Create: `.github/workflows/oracle-deploy.yml`
- Create: `docs/OPERATIONS.md`
- Modify: `tests/test_oracle_deployment.py`
- Create: `tests/test_operations_docs.py`

**Interfaces:**
- `render_oracle_bundle(...)` emits systemd service, environment loader reference, health command, restart policy, and logrotate config.
- `oracle-deploy.yml` is manual-only and requires GitHub Environment `oracle` plus `ORACLE_ENABLED=true`.
- Local run instructions support Windows development and Linux production nodes.

- [ ] **Step 1: Extend Oracle tests and operations-doc assertions**

Assert service runs `mastertrd.live_node`, restarts on failure, reads secrets from an external environment file, never embeds a credential, and deployment workflow cannot run unless Oracle is explicitly enabled.

- [ ] **Step 2: Run tests and confirm RED on missing deployment workflow/docs**

Run: `uv run pytest tests/test_oracle_deployment.py tests/test_operations_docs.py -v`
Expected: FAIL because deployment workflow/docs are incomplete.

- [ ] **Step 3: Implement deployment workflow and operator documentation**

Document PAPER, DEMO, TESTNET, LIVE startup, recovery, log locations, emergency kill, rollback, secret rotation, and exact owner inputs. State explicitly that Vercel is unsuitable for the persistent low-latency execution node; it may host a future read-only dashboard/API only.

- [ ] **Step 4: Run Oracle and security regressions**

Run: `uv run pytest tests/test_oracle_deployment.py tests/test_operations_docs.py tests/test_credentials.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mastertrd/oracle.py .github/workflows/oracle-deploy.yml docs/OPERATIONS.md tests/test_oracle_deployment.py tests/test_operations_docs.py
git commit -m "ops: complete Oracle and local deployment package"
```

---

### Task 13: Final cumulative acceptance, clean-clone proof, and exact-SHA report

**Files:**
- Modify: `src/mastertrd/acceptance.py`
- Create: `docs/ACCEPTANCE_REPORT.md`
- Modify: `README.md`

**Interfaces:**
- `run_full_acceptance(...) -> AcceptanceReport` records exact commit SHA, lock hash, test suites, dataset fixtures, engine versions, skipped credential-gated probes, and whether LIVE is eligible.
- A skipped credential-gated testnet probe must be reported as `BLOCKED_OWNER_INPUT`, never PASS.

- [ ] **Step 1: Add final acceptance-report tests**

Assert an acceptance report cannot say `COMPLETE` when any mandatory non-credential gate fails, and cannot say `LIVE_ELIGIBLE` when testnet/reconciliation/kill-switch/risk-review evidence is absent.

- [ ] **Step 2: Run final acceptance tests and confirm RED until all earlier tasks are present**

Run: `uv run pytest tests/test_acceptance.py -v`
Expected: RED until the report aggregates every mandatory gate.

- [ ] **Step 3: Run the complete cumulative suite**

Run:

```bash
uv sync --frozen --all-extras
uv run pytest -q
uv run python -m mastertrd.acceptance --write docs/ACCEPTANCE_REPORT.md
```

Expected: all non-credential suites PASS. Credential-gated demo/testnet probes either PASS with owner-supplied GitHub secrets or are explicitly `BLOCKED_OWNER_INPUT`. LIVE remains disabled by default.

- [ ] **Step 4: Verify clean-clone install and public-repo safety**

From a fresh checkout of the completion branch, run `uv sync --frozen --all-extras`, full pytest, secret-pattern scan, dependency audit, and acceptance generation. Confirm no `.env`, keys, account identifiers, balances, private positions, or raw sensitive payloads exist in tracked files.

- [ ] **Step 5: Commit exact-head acceptance report**

```bash
git add src/mastertrd/acceptance.py docs/ACCEPTANCE_REPORT.md README.md
git commit -m "docs: record MasterTrd cumulative acceptance"
```

---

## Completion Standard

This plan is complete only when Tasks 1–13 are implemented and cumulative tests are green on one exact commit. Missing exchange/testnet credentials or Oracle host details are reported as owner-input blockers, not hidden as implementation completion. The code may be implementation-complete for LIVE while LIVE remains disabled and unactivated. No task may weaken `MASTER_PLAN.md` to obtain a green result.
