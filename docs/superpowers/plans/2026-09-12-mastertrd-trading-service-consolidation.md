# MasterTrd Trading Service Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated local app/status/operator runtime wrappers with one public `TradingService` boundary while preserving the existing Nautilus PAPER/DEMO/TESTNET/LIVE execution, risk, reconciliation, recovery, and LIVE fail-closed semantics.

**Architecture:** `TradingService` becomes the only consumer/operator-facing service for runtime status, strategy catalog, preflight, and persistent execution lifecycle. `runtime_factory.py`, `execution_runtime.py`, `paper_session.py`, risk, reconciliation, and Nautilus adapters remain internal proven primitives in this slice. `live_node.py` becomes a tiny compatibility entrypoint and `mastertrd trading` becomes the canonical local worker command.

**Tech Stack:** Python 3.13, pytest, NautilusTrader, Streamlit, uv.

**Spec:** `docs/superpowers/specs/2026-09-12-mastertrd-thin-core-local-first-design.md`

## Global Constraints

- PAPER remains the default and requires no exchange execution credential.
- LIVE remains fail-closed and still requires explicit `MASTERTRD_MODE=LIVE` plus `LIVE_TRADING_ENABLED=true` and provider credentials/admission gates.
- No direct order submission is added to the Streamlit process.
- Existing execution runtime, risk runtime, reconciliation, restart/recovery, and PAPER journal semantics are not rewritten in this slice.
- Multi-strategy behavior is not narrowed; this boundary must remain compatible with running multiple isolated strategy workers until the later shared-portfolio worker slice replaces that mechanism.
- No Oracle/cloud runtime path is reintroduced.

---

### Task 1: Add the unified trading-service contract

**Files:**
- Create: `src/mastertrd/trading_service.py`
- Create: `tests/test_trading_service.py`
- Modify: `tests/test_runtime_shutdown.py`

**Interfaces:**
- Produces: `TradingReadiness`, `TradingService.snapshot()`, `TradingService.strategy_rows()`, `TradingService.preflight()`, `TradingService.run()`, `TradingService.run_forever()`.
- Consumes: `RuntimeConfig`, `build_execution_runtime`, `load_binance_credentials`, existing strategy catalog.

- [ ] **Step 1: Write failing tests**

Add tests that import `TradingService`, prove PAPER defaults are safe, DEMO/TESTNET/LIVE credential preflight remains fail-closed, the strategy catalog is unchanged, injected execution runtimes are closed on success and failure, and `run_forever()` registers SIGINT/SIGTERM.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_trading_service.py tests/test_runtime_shutdown.py`
Expected: FAIL because `mastertrd.trading_service` does not exist.

- [ ] **Step 3: Implement the minimal service**

Create the service as the public facade over existing runtime primitives. Do not duplicate execution logic from `ExecutionRuntime`; only own configuration/preflight/lifecycle and read-model concerns.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_trading_service.py tests/test_runtime_shutdown.py tests/integration/test_runtime_factory.py`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "refactor: add unified trading service"`

---

### Task 2: Move local app and CLI onto the trading service

**Files:**
- Modify: `src/mastertrd/cli.py`
- Modify: `src/mastertrd/local_app.py`
- Delete: `src/mastertrd/app_service.py`
- Delete: `tests/test_app_service.py`
- Modify: `tests/test_consumer_local_smoke.py`

**Interfaces:**
- Consumes: `TradingService.snapshot()`, `TradingService.strategy_rows()`, `TradingService.run_forever()`.
- Produces: canonical `mastertrd trading` worker command.

- [ ] **Step 1: Write failing CLI/app tests**

Require `mastertrd trading` in parser/help and require app/CLI source to import `TradingService`, not `AppService`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_consumer_local_smoke.py tests/test_trading_service.py`
Expected: FAIL because the CLI/app still use `AppService` and no `trading` command exists.

- [ ] **Step 3: Switch consumers and remove `AppService`**

Use `TradingService` in both local surfaces and route the new CLI subcommand to `run_forever()`.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_consumer_local_smoke.py tests/test_trading_service.py tests/test_cli.py 2>/dev/null || uv run pytest -q tests/test_consumer_local_smoke.py tests/test_trading_service.py`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "refactor: route local control through trading service"`

---

### Task 3: Collapse the legacy node/status wrappers

**Files:**
- Modify: `src/mastertrd/live_node.py`
- Delete: `src/mastertrd/paper_status.py`
- Delete: `tests/test_live_node.py`
- Modify: `tests/test_paper_status.py`
- Modify: `tests/test_final_paper_hardening.py`
- Modify: `tests/test_local_runtime_contract.py`
- Modify: `tests/test_plan_closure_cleanup.py`

**Interfaces:**
- `live_node.main()` remains as a compatibility entrypoint and delegates directly to `TradingService.run_forever()`.
- PAPER status calculation moves behind `TradingService.paper_status_payload()` so the local app/service owns the read model.

- [ ] **Step 1: Add parity assertions first**

Move the existing PAPER status expectations and node lifecycle expectations to `tests/test_trading_service.py`/`tests/test_paper_status.py`, importing the new service API.

- [ ] **Step 2: Verify RED where the old wrapper is still authoritative**

Run the focused tests and confirm at least one assertion fails until the delegation/status move is made.

- [ ] **Step 3: Slim/delete wrappers**

Reduce `live_node.py` to the compatibility module entrypoint, move the pure PAPER status payload behavior into `TradingService`, and delete the standalone `paper_status.py` CLI/module.

- [ ] **Step 4: Verify parity**

Run: `uv run pytest -q tests/test_trading_service.py tests/test_paper_status.py tests/test_final_paper_hardening.py tests/test_runtime_shutdown.py tests/test_local_runtime_contract.py tests/test_plan_closure_cleanup.py tests/integration/test_runtime_factory.py tests/integration/test_runtime_recovery.py`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "refactor: collapse trading operator wrappers"`

---

### Task 4: Make the local trading boundary authoritative in docs and progress

**Files:**
- Modify: `README.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/THIN_CORE_PROGRESS.md`
- Modify: `docs/THIN_CORE_INVENTORY.md`
- Modify: `tests/test_operations_docs.py`

- [ ] **Step 1: Write/update doc contract assertions**

Require `mastertrd trading` as the canonical persistent worker command and keep explicit PAPER/LIVE safety strings.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_operations_docs.py tests/test_local_runtime_contract.py`
Expected: FAIL until docs are updated.

- [ ] **Step 3: Update docs/progress/inventory**

Record the completed trading-service slice, keep LIVE locked, and set the next incomplete slice to shared multi-strategy portfolio/risk worker consolidation rather than operator-wrapper cleanup.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_operations_docs.py tests/test_local_runtime_contract.py`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "docs: make trading service the local runtime boundary"`

---

### Task 5: Full verification and push readiness

- [ ] Run `uv lock --check`.
- [ ] Run `uv pip check`.
- [ ] Run `uv run pytest -q` and record the exact pass/warning count.
- [ ] Run an active-reference audit proving `AppService` and `mastertrd.paper_status` have zero source/test call-sites and `live_node.py` contains only compatibility startup code.
- [ ] Compare source/test/workflow line counts against baseline commit `ee04dd2` and the prior checkpoint.
- [ ] Run `git status --short --branch` and `git log --oneline -8`.
- [ ] Push `feat/thin-core-local-first-20260912` only if all verification is green and the worktree is clean.
