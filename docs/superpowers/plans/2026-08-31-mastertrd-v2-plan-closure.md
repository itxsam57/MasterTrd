# MasterTrd V2 Plan-Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Completed steps use checked checkbox (`- [x]`) syntax for tracking.

**Goal:** Close every gap between `MASTER_PLAN.md` and real executable behavior so MasterTrd is process-ready for autonomous research, forward PAPER, DEMO/TESTNET, guarded LIVE eligibility, and specialist strategy families without weakening any safety gate.

**Architecture:** Keep NautilusTrader as the sole authoritative execution engine. Build bottom-up: executable strategy semantics first; family/product-specific execution second; live risk-state ownership third; persistent runtime and forward-paper lifecycle next; autonomous research/specialist orchestration after those foundations; candidate-bound testnet/live evidence and strict acceptance last. Every layer must fail closed when required market data, product metadata, credentials, or runtime evidence is unavailable.

**Tech Stack:** Python 3.13, pytest, NautilusTrader, VectorBT, Optuna, pymoo, TA-Lib, statsmodels, arch, ruptures, River, skfolio, QuantStats, hftbacktest, DuckDB, Parquet, Binance public data, ccxt data fallback, GitHub Actions.

**Spec:** `MASTER_PLAN.md`

## Global Constraints

- NautilusTrader remains the only authoritative order/execution engine.
- `LIVE_TRADING_ENABLED=false` remains the default; no PAPER/DEMO/TESTNET fallback may activate LIVE.
- Exchange keys must never have withdrawal permission and secrets/private account state never enter git.
- Promotion state may advance only through the Promotion Governor.
- HFT/scalping/order-book/market-making promotion requires real integrity-checked tick/L2 evidence; candle-only evidence never substitutes.
- Production order risk must use owned runtime state, not permissive zero/default snapshots.
- Research and execution must share strategy semantics so optimization cannot validate behavior the executor does not run.
- Missing external inputs (real credentials, venue support, L2 datasets, Oracle host) are explicit blockers, never synthetic PASS results.
- Each production behavior change follows RED -> GREEN -> subsystem regression -> cumulative exact-head verification.
- A feature is not complete until its real process path is executable and the V2 acceptance matrix proves it.

---

### Task 1: Make StrategyGenome semantics executable and parity-tested

**Files:**
- Modify: `src/mastertrd/execution_signals.py`
- Create: `src/mastertrd/execution_policy.py`
- Modify: `src/mastertrd/nautilus_bar_strategy.py`
- Modify: `src/mastertrd/nautilus_multileg_strategy.py`
- Modify: `src/mastertrd/nautilus_options_strategy.py`
- Modify: `src/mastertrd/research/screen.py`
- Create: `tests/test_execution_policy.py`
- Create: `tests/test_execution_signal_parity.py`
- Modify: `tests/integration/test_nautilus_strategy_activity.py`

**Interfaces:**
- Produce `PositionState` and `ExecutionDecision` representing target side/legs plus explicit close/stop/take-profit/trailing behavior.
- Produce `evaluate_execution_policy(genome, market_state, position_state) -> ExecutionDecision` and use the same implementation in VectorBT screening and Nautilus strategies.
- Implement declared exits: `cross_reverse`, `atr_bracket`, `mean_or_atr_stop`, `trailing_atr`, `spread_mean_exit`, `edge_decay`, `rebalance`, `greeks_or_time_exit`, and HFT-specific exit contracts consumed by Task 3.

- [x] Write failing tests proving each generated exit changes a real open position at the configured condition and unsupported exits fail closed.
- [x] Write TA-Lib parity tests for EMA, RSI, ATR, Donchian and z-score calculations at `1e-9` tolerance where applicable.
- [x] Run focused tests and record RED because current strategies use entry-direction changes and largely ignore `genome.exit`.
- [x] Implement shared execution policy; remove duplicated signal/exit calculations from research/execution adapters.
- [x] Run focused, family compiler, strategy activity, screening, robustness and cumulative core suites GREEN.

---

### Task 2: Make multi-leg sizing and product contracts real

**Files:**
- Modify: `src/mastertrd/strategy_families.py`
- Modify: `src/mastertrd/nautilus_strategy.py`
- Modify: `src/mastertrd/nautilus_multileg_strategy.py`
- Modify: `src/mastertrd/nautilus_options_strategy.py`
- Modify: `src/mastertrd/nautilus_evaluation.py`
- Create: `src/mastertrd/product_contracts.py`
- Create: `tests/test_product_contracts.py`
- Modify: `tests/integration/test_nautilus_family_compilers.py`
- Create: `tests/integration/test_multileg_evaluation.py`

**Interfaces:**
- Produce `validate_product_compatibility(genome, instruments) -> None`.
- Produce `run_nautilus_evaluation(genome, *, instruments, data_by_instrument, ...) -> EvaluationResult` supporting single and multi-instrument candidates.
- Multi-leg order quantity must derive from decision leg weights/hedge ratio and instrument precision, not one equal hard-coded trade size.
- Options compilation must require actual option-compatible instrument metadata and defined-risk policy; spot/future instruments must fail closed.

- [x] Write RED tests for hedge-ratio quantities, missing instrument legs, spot-as-option rejection and true multi-leg evaluation.
- [x] Implement product compatibility and multi-instrument evaluator using one Nautilus engine.
- [x] Replace single-instrument assumptions in robustness/hidden/transfer paths with the generalized evaluator.
- [x] Run all family compilers/evaluations and cumulative tests GREEN.

---

### Task 3: Add authoritative Nautilus specialist execution for HFT families

**Files:**
- Create: `src/mastertrd/hft_strategy.py`
- Modify: `src/mastertrd/nautilus_strategy.py`
- Modify: `src/mastertrd/hft_validation.py`
- Modify: `src/mastertrd/research/hft_specialist.py`
- Modify: `src/mastertrd/data/orderbook.py`
- Create: `tests/test_hft_strategy.py`
- Modify: `tests/integration/test_real_l2_hft_gate.py`
- Create: `tests/integration/test_hft_nautilus_execution.py`

**Interfaces:**
- Produce `compile_hft_genome_to_nautilus(...)` for `scalping`, `grid`, `market_making`, `order_book`, `cross_venue_arb`.
- Nautilus owns live/paper order lifecycle; `hftbacktest` remains validation-only.
- HFT execution consumes tick/L2 state and the Task 1 execution policy; no candle fallback.

- [x] Write RED tests proving every HFT family compiles to a Nautilus specialist strategy and rejects BAR-only inputs.
- [x] Implement tick/L2 strategy state, quote/order intents, inventory/exit handling and mandatory risk hook.
- [x] Keep real-L2 validation identity-bound and synthetic stress `supporting_only=True`.
- [x] Run HFT engine, real-L2, execution, risk and cumulative suites GREEN.

---

### Task 4: Feed the risk governor real execution state

**Files:**
- Create: `src/mastertrd/risk_state.py`
- Modify: `src/mastertrd/nautilus_risk_hook.py`
- Modify: `src/mastertrd/risk_runtime.py`
- Modify: `src/mastertrd/execution_runtime.py`
- Modify: `tests/test_risk_runtime.py`
- Create: `tests/test_risk_state.py`
- Modify: `tests/integration/test_risk_execution_hook.py`

**Interfaces:**
- Produce `RiskStateProvider.snapshot(intent, reference_price) -> RiskSnapshot`.
- Snapshot must supply real symbol/portfolio exposure, daily PnL, drawdown, leverage, correlated exposure, spread, realized volatility, market-data age, reconciliation status/age and venue/API health.
- Missing mandatory state in DEMO/TESTNET/LIVE must fail closed; historical backtest may use an explicitly named simulation provider.

- [x] Write RED tests proving nonzero account/market state reaches `RiskRuntime.check_order` and stale/missing state kills or blocks as policy requires.
- [x] Implement provider adapters and remove zero/healthy production defaults from `NautilusRiskMixin`.
- [x] Wire reconciliation/API/market-state updates to the provider.
- [x] Run risk, execution and live-readiness regressions GREEN.

---

### Task 5: Build the repository-owned persistent execution runtime

**Files:**
- Create: `src/mastertrd/runtime_factory.py`
- Create: `src/mastertrd/binance_stream.py`
- Modify: `src/mastertrd/live_node.py`
- Modify: `src/mastertrd/execution_runtime.py`
- Modify: `src/mastertrd/nautilus_paper.py`
- Modify: `src/mastertrd/reconciliation.py`
- Modify: `tests/test_streaming.py`
- Modify: `tests/integration/test_paper_live_feed.py`
- Modify: `tests/integration/test_runtime_recovery.py`
- Create: `tests/integration/test_runtime_factory.py`

**Interfaces:**
- Produce `build_execution_runtime(runtime: RuntimeConfig, environ: Mapping[str,str]) -> ExecutionRuntime` as the canonical factory.
- `live_node.main()` uses the canonical factory by default; arbitrary `MASTERTRD_EXECUTION_FACTORY` is removed from production requirements.
- PAPER uses real Binance public market data plus Nautilus sandbox execution; DEMO/TESTNET/LIVE use Nautilus Binance adapters and mode-specific credentials.
- Restart recovery restores journal/state and reconciles before accepting new risk.

- [x] Write RED tests showing CLI/service boot works without an external arbitrary factory and that unreconciled recovery cannot dispatch orders.
- [x] Implement public stream reconnect/backoff/idempotency, runtime construction and mode adapters.
- [x] Prove PAPER process path with deterministic recorded public-feed fixture and Nautilus fills; keep real-network smoke separate.
- [x] Run runtime/recovery/reconciliation/security suites GREEN.

---

### Task 6: Make forward PAPER -> CHALLENGER -> CHAMPION operational

**Files:**
- Modify: `src/mastertrd/paper_cycle.py`
- Modify: `src/mastertrd/paper_forward.py`
- Modify: `src/mastertrd/paper_archive.py`
- Modify: `src/mastertrd/paper_challenger.py`
- Modify: `src/mastertrd/champion.py`
- Create: `src/mastertrd/forward_scheduler.py`
- Create: `tests/integration/test_forward_paper_lifecycle.py`
- Create: `tests/integration/test_champion_lifecycle.py`

**Interfaces:**
- PAPER start remains an explicit start event, not proof of minimum forward evidence.
- Produce/archive provenance-verified `PaperForwardReport` from real persistent PAPER sessions.
- Scheduler evaluates `paper_minimum_evidence`, promotes through Governor, compares challengers against incumbent evidence, and never skips a lifecycle state.

- [x] Write RED lifecycle test from `HIDDEN_PASS` through real PAPER reports to CHALLENGER and CHAMPION.
- [x] Implement report finalization/archive/scheduler against the Task 5 runtime.
- [x] Prove restart/resume does not duplicate trades or reports.
- [x] Run paper/champion/governor/cumulative suites GREEN.

---

### Task 7: Make ResearchBrain family-aware and run specialist gates

**Files:**
- Modify: `src/mastertrd/research_brain.py`
- Modify: `src/mastertrd/research/generator.py`
- Modify: `src/mastertrd/research/screen.py`
- Modify: `src/mastertrd/robustness_cycle.py`
- Modify: `src/mastertrd/hidden_cycle.py`
- Modify: `src/mastertrd/multi_leg_validation.py`
- Modify: `src/mastertrd/options_validation.py`
- Create: `src/mastertrd/specialist_orchestrator.py`
- Modify: `tests/integration/test_autonomous_research_cycle.py`
- Create: `tests/integration/test_research_all_families.py`

**Interfaces:**
- Family-aware generation assigns one instrument to single-leg families, compatible instrument sets to multi-leg/cross-venue families, option instruments to options, and tick/L2 datasets to HFT families.
- Specialist stage executes required evidence producers; it may quarantine only on failed/missing evidence, not merely because evidence is required.
- Research screening may use appropriate cheap family screens but must never fake execution compatibility.

- [x] Write RED tests proving representative candidates from every registered family reach the appropriate screen/validation/specialist path instead of structural rejection.
- [x] Implement family-aware universe construction and specialist orchestrator.
- [x] Feed multi-leg/HFT/options evidence into Governor promotions using exact candidate/data/code identities.
- [x] Store failures with machine-readable root reasons and retain idempotent stage receipts.
- [x] Run all research/robustness/hidden/specialist suites GREEN.

---

### Task 8: Broaden scheduled autonomous research safely

**Files:**
- Modify: `.github/workflows/autonomous-research.yml`
- Modify: `tests/test_workflow_policy.py`
- Create: `src/mastertrd/research_job.py`
- Create: `tests/test_research_job.py`

**Interfaces:**
- Workflow calls a checked-in job entrypoint rather than embedding a one-family Python program in YAML.
- Job loads configured safe research families/universes, downloads checksum-verified public datasets, runs ResearchBrain and emits public-safe artifacts only.
- HFT/options families without qualifying public data are recorded as blocked, not silently substituted.

- [x] Write RED workflow/job tests proving production automation is not hard-coded to trend/ETH/one seed.
- [x] Implement checked-in job configuration and public-safe artifact contract.
- [x] Run workflow policy/security/research stack GREEN.

---

### Task 9: Bind TESTNET/live evidence to the actual champion

**Files:**
- Modify: `src/mastertrd/live_evidence.py`
- Modify: `src/mastertrd/live_readiness.py`
- Modify: `.github/workflows/testnet-smoke.yml`
- Create: `src/mastertrd/testnet_candidate.py`
- Modify: `tests/test_live_evidence.py`
- Modify: `tests/test_live_readiness.py`
- Create: `tests/integration/test_candidate_testnet_bundle.py`

**Interfaces:**
- TESTNET job accepts/loads a public-safe candidate manifest containing exact strategy/genome/code/dataset identities and non-secret product/order parameters.
- Risk review, reconciliation, kill-switch and real testnet smoke share the same identity bundle required by `live_evidence_bundle_identity_ok`.
- Generic system-smoke evidence remains diagnostic and cannot promote a real champion.

- [x] Write RED tests proving generic smoke cannot satisfy a champion and coherent candidate-bound evidence can.
- [x] Implement candidate manifest verification and mode-specific real Nautilus testnet submission adapter.
- [x] Keep missing credentials as `CREDENTIALS_UNAVAILABLE/BLOCKED_OWNER_INPUT`.
- [x] Run governor/live-readiness/workflow/security suites GREEN.

---

### Task 10: Remove dead/duplicate code and false completion claims

**Files:**
- Modify: `src/mastertrd/nautilus_risk_hook.py`
- Modify: `src/mastertrd/risk_profiles.py`
- Modify: `README.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/ACCEPTANCE_REPORT.md`
- Modify: relevant tests

**Interfaces:**
- Remove unused legacy `default_nautilus_risk_limits()` after proving no production/test callers remain.
- Remove compatibility shims/config knobs made obsolete by Tasks 1-9, but only after repository-wide usage verification.
- Documentation must distinguish implemented/process-ready features from owner-input blockers.

- [x] Search for dead symbols, duplicate abstractions, unused workflow/config paths and stale docs.
- [x] Write/adjust regression tests before deleting behavior-bearing code.
- [x] Remove proven-dead code and simplify imports/contracts.
- [x] Run full suite and public-repo security GREEN.

---

### Task 11: Replace weak completion status with a V2 master-plan acceptance matrix

**Files:**
- Modify: `src/mastertrd/acceptance.py`
- Modify: `.github/workflows/acceptance.yml`
- Create: `src/mastertrd/capability_matrix.py`
- Create: `tests/test_capability_matrix.py`
- Modify: `tests/test_acceptance.py`
- Modify: `README.md`
- Modify: `docs/ACCEPTANCE_REPORT.md`

**Interfaces:**
- Produce `CapabilityCheck(capability, passed, evidence, blocker)` for every mandatory `MASTER_PLAN.md` capability.
- `implementation_status=COMPLETE` requires all code-owned/process-owned mandatory capabilities PASS, not merely generic suite receipts.
- External owner inputs may be explicit blockers for activation/evidence but may not hide missing implementation.
- Exact-head acceptance records family coverage, executable exits, multi-leg/options/HFT execution, risk-state ownership, persistent runtime, forward PAPER lifecycle, specialist ResearchBrain, candidate-bound testnet interface, security, reproducibility and deployment artifacts.

- [x] Write RED acceptance tests reproducing the current false-positive case: generic suites GREEN while a required capability is absent must yield `FAILED`.
- [x] Implement capability matrix and workflow evidence collection.
- [x] Run acceptance against the V2 branch; resolve every code-owned failure rather than suppressing it.
- [x] Run clean exact-SHA locked install, full tests/coverage, all stack workflows, security scan and acceptance artifact.
- [x] Only after every code/process capability is PASS may README/docs say V2 implementation is COMPLETE. LIVE activation remains separately gated by real candidate-bound TESTNET evidence, Governor approval and owner-controlled LIVE configuration.

---

## V2 completion rule

Do not mark this plan complete because modules exist, tests compile, or generic CI is green. Completion requires all eleven tasks above to be checked off with exact-head evidence, every advertised strategy family routed through a real compatible research/validation/execution path, executable entry/exit/risk semantics, a repository-owned persistent PAPER/DEMO/TESTNET runtime, operational PAPER->CHALLENGER->CHAMPION progression, candidate-bound live-readiness evidence interfaces, no known dead/duplicate production code, and the V2 capability matrix reporting no code-owned blocker.

## Closure evidence

- Implementation status: `PROCESS_READY`
- Code/process capability matrix: all mandatory capabilities PASS in `Completion Acceptance`; the exact-head workflow artifact remains canonical for the current branch SHA.
- `testnet_smoke` remains `BLOCKED_OWNER_INPUT`; real protected Binance TESTNET credentials and a manual `Testnet Smoke` workflow dispatch are required before venue evidence can exist.
- LIVE eligible: `false`; Promotion Governor approval remains `false` until a coherent real TESTNET evidence bundle exists.
