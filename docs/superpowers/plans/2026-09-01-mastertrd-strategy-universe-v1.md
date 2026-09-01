# MasterTrd Strategy Universe V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a versioned strategy/evidence universe and provider capability map that immediately broadens safe research while preserving exact execution semantics and all existing safety gates.

**Architecture:** Add a standalone strategy-universe registry and deterministic recipe compiler on top of the existing `StrategyGenome` model. Keep the legacy family generator backward compatible, allow scheduled BAR research to select exact executable recipes, and separately record provider/adaptor capabilities without claiming runtime admission. Non-executable ideas remain cataloged with machine-readable blockers until their primitive/data/provider gate is implemented.

**Tech Stack:** Python 3.13, pytest, existing MasterTrd `StrategyGenome`, NautilusTrader 1.231.0, GitHub Actions, Binance public data.

**Spec:** `docs/superpowers/specs/2026-09-01-mastertrd-strategy-universe-v1-design.md`

## Global Constraints

- NautilusTrader remains the only authoritative execution engine.
- Existing strategy execution behavior must not change unless a new failing regression test requires it.
- `LIVE_TRADING_ENABLED=false` remains the default.
- No outside strategy code is copied into MasterTrd; only concepts/provenance metadata are recorded.
- A recipe may enter promotion-grade research only when its readiness is `EXECUTABLE` and its family data requirements are satisfied.
- HFT/scalping/order-book/market-making recipes still require real tick/L2 evidence for promotion.
- Options recipes still require true option instruments and option evidence.
- Provider capability and MasterTrd provider admission are separate facts.
- Missing data/provider/credential requirements remain explicit blockers rather than synthetic PASS results.
- All behavior changes follow RED -> GREEN -> focused regression -> cumulative exact-head CI.

---

### Task 1: Strategy source and recipe registry

**Files:**
- Create: `src/mastertrd/strategy_universe.py`
- Create: `tests/test_strategy_universe.py`

**Interfaces:**
- Produce `EvidenceGrade`, `RecipeReadiness`, `AssetClass`, `TradingHorizon`, `StrategySource`, `StrategyRecipe`.
- Produce `STRATEGY_SOURCES`, `STRATEGY_RECIPES`.
- Produce `strategy_recipe(recipe_id: str) -> StrategyRecipe`.
- Produce `recipes_for(*, family: str | None = None, asset_class: AssetClass | None = None, readiness: RecipeReadiness | None = None) -> tuple[StrategyRecipe, ...]`.

- [ ] **Step 1: Write failing registry tests** proving IDs are unique, all source references resolve, every family exists, every executable recipe uses a current executable primitive/exit pair, blocked recipes expose a non-empty blocker, and the catalog spans crypto/equity/FX/futures/options/prediction/betting/multi-asset markets.
- [ ] **Step 2: Run `pytest -q tests/test_strategy_universe.py` and verify RED** because the module does not exist.
- [ ] **Step 3: Implement the source/recipe dataclasses and V1 catalog** with at least 100 named research recipes/targets and at least 30 immediately executable exact recipes using current MasterTrd primitives.
- [ ] **Step 4: Run `pytest -q tests/test_strategy_universe.py` GREEN.**

### Task 2: Deterministic recipe compiler and legacy generator compatibility

**Files:**
- Modify: `src/mastertrd/strategy_universe.py`
- Modify: `src/mastertrd/research/generator.py`
- Create: `tests/test_strategy_recipe_compiler.py`
- Modify: `tests/test_strategy_generator.py`

**Interfaces:**
- Produce `compile_strategy_recipe(recipe_id: str, *, instruments: Sequence[str], seed: int, trade_size: str | None = None) -> StrategyGenome`.
- Extend `generate_candidate(..., recipe_id: str | None = None) -> StrategyGenome` while preserving existing calls.

- [ ] **Step 1: Write failing compiler tests** proving deterministic recipe compilation, distinct recipe identity, parameter bounds, family/instrument validation, trade-size validation, and fail-closed behavior for non-executable recipes.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Implement deterministic range sampling and recipe compilation using only existing entry/exit semantics.**
- [ ] **Step 4: Wire optional `recipe_id` into `generate_candidate` without changing the no-recipe path.**
- [ ] **Step 5: Run `pytest -q tests/test_strategy_recipe_compiler.py tests/test_strategy_generator.py` GREEN.**

### Task 3: Provider and tradable-market capability registry

**Files:**
- Create: `src/mastertrd/market_capabilities.py`
- Create: `tests/test_market_capabilities.py`
- Create: `docs/MARKET_PROVIDER_MATRIX.md`

**Interfaces:**
- Produce `ProviderKind`, `MasterTrdAdmission`, `ProviderCapability`, `PROVIDER_CAPABILITIES`.
- Produce `provider_capability(provider_id: str) -> ProviderCapability` and filters by asset/instrument/execution/data support.
- The matrix must distinguish Nautilus availability from MasterTrd admission.

- [ ] **Step 1: Write failing capability tests** proving Binance is admitted, data-only providers cannot claim execution, Polymarket/Betfair/Interactive Brokers are represented but not silently admitted, and the registry covers crypto CEX/DEX, equities, FX, futures, options, prediction markets, betting, and external data.
- [ ] **Step 2: Run `pytest -q tests/test_market_capabilities.py` and verify RED.**
- [ ] **Step 3: Implement the capability registry from locked NautilusTrader 1.231.0/current stable integration documentation.**
- [ ] **Step 4: Write the public matrix with admission priority and credential/data blockers, without secrets.**
- [ ] **Step 5: Run focused tests GREEN.**

### Task 4: Broaden scheduled public-data research by recipe

**Files:**
- Modify: `src/mastertrd/research_job.py`
- Modify: `tests/test_research_job.py`

**Interfaces:**
- Extend `ResearchJobPlan` with `runnable_recipe_ids: tuple[str, ...]`.
- Public run payloads record `recipe_id`.
- Default scheduled research uses executable BAR recipes compatible with current Binance public spot data and explicitly leaves multi-leg/options/HFT/provider-blocked recipes blocked.

- [ ] **Step 1: Write failing tests** proving the default plan contains multiple recipes per runnable family, every scheduled recipe is `EXECUTABLE`, and no tick/L2/options/provider-required recipe leaks into the BAR job.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Update job planning/execution to iterate deterministic recipe IDs and seeds while reusing timeframe/data caches.**
- [ ] **Step 4: Keep artifact payload public-safe and add recipe identity.**
- [ ] **Step 5: Run `pytest -q tests/test_research_job.py tests/test_workflow_policy.py` GREEN.**

### Task 5: Family-wide integration and Champion traceability

**Files:**
- Modify: `tests/integration/test_research_all_families.py`
- Create: `tests/integration/test_strategy_universe_research.py`
- Modify: `README.md`

**Interfaces:**
- Prove representative executable recipes enter the same ResearchBrain, specialist and Governor paths as legacy generated candidates.
- Preserve strategy/genome/data/code identity and include recipe provenance in research artifacts without changing promotion state rules.

- [ ] **Step 1: Write RED integration tests** for representative trend, breakout, mean-reversion, stat-arb, options and HFT recipe handling; data-blocked specialist cases must remain blocked rather than proxied.
- [ ] **Step 2: Implement only the minimal plumbing needed for recipe traceability.**
- [ ] **Step 3: Run focused integration suites GREEN.**
- [ ] **Step 4: Document Strategy Universe V1 and the provider-admission boundary in `README.md`.**

### Task 6: Cumulative verification and PR handoff

**Files:**
- No new production interface unless a regression exposes a root-cause defect.

- [ ] **Step 1: Run the focused strategy-universe, generator, research-job, provider and research integration suites.**
- [ ] **Step 2: Run cumulative `pytest -q`.**
- [ ] **Step 3: Run exact-head CI/research/full-stack/security/acceptance workflows through the normal branch/PR path.**
- [ ] **Step 4: Review failures from the bottom/root cause; do not weaken thresholds or suppress blockers.**
- [ ] **Step 5: Open a PR only after the branch is internally coherent and report the exact verified head.**
