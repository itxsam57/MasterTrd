# MasterTrd Local Runtime Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the superseded Oracle/GitHub operator runtime path and leave one local-first runtime/documentation contract without weakening PAPER/LIVE safety.

**Architecture:** The local app, local scheduler, `mastertrd.live_node`, Nautilus execution, and existing risk/reconciliation paths remain. Oracle deployment/status modules and workflows are deleted because they have no active source call-sites; local status and recovery documentation become authoritative.

**Tech Stack:** Python 3.13, pytest, NautilusTrader, Streamlit, DuckDB/Parquet, GitHub for source/optional CI only.

**Spec:** `docs/superpowers/specs/2026-09-12-mastertrd-thin-core-local-first-design.md`

## Global Constraints

- Local PC is the required runtime; no Vercel/PostHog/Neon/Oracle/GitHub-hosted runtime dependency.
- Keep research, PAPER, TESTNET, and provider-gated LIVE capability.
- Keep `LIVE_TRADING_ENABLED=false` fail-closed behavior.
- Do not delete risk, reconciliation, recovery, promotion, or provider-admission behavior.
- Historical Oracle specs/plans remain as provenance; active product docs stop instructing Oracle deployment.
- `asset_transfer.py` is KEEP because active research modules import it.

---
### Task 1: Lock the local-only runtime contract

**Files:**
- Create: `tests/test_local_runtime_contract.py`
- Modify: `docs/THIN_CORE_INVENTORY.md`

**Interfaces:**
- Consumes: current local app/scheduler contract.
- Produces: a regression that rejects Oracle runtime files/workflows while preserving local LIVE/PAPER modules.

- [ ] **Step 1: Write the failing contract test**

```python
from pathlib import Path


def test_runtime_has_no_oracle_product_path():
    for path in (
        "src/mastertrd/oracle.py",
        "src/mastertrd/oracle_paper_status.py",
        "src/mastertrd/paper_diagnostics.py",
        ".github/workflows/oracle-deploy.yml",
        ".github/workflows/paper-status.yml",
    ):
        assert not Path(path).exists()
    assert Path("src/mastertrd/live_node.py").exists()
    assert Path("src/mastertrd/asset_transfer.py").exists()
```
- [ ] **Step 2: Run and confirm RED**

Run: `uv run pytest -q tests/test_local_runtime_contract.py`
Expected: FAIL because Oracle runtime files/workflows still exist.

- [ ] **Step 3: Correct the cleanup inventory**

Change `asset_transfer.py` from DELETE to KEEP with the reason that `research_brain.py`, `research_job.py`, and `robustness_cycle.py` import it. Mark Oracle modules/workflows and `paper_diagnostics.py` as DELETE because their only remaining consumers are the legacy Oracle path/tests.

- [ ] **Step 4: Commit the contract/inventory**

```bash
git add tests/test_local_runtime_contract.py docs/THIN_CORE_INVENTORY.md
git commit -m "test: lock local-only runtime boundary"
```

### Task 2: Delete Oracle/operator runtime code

**Files:**
- Delete: `src/mastertrd/oracle.py`
- Delete: `src/mastertrd/oracle_paper_status.py`
- Delete: `src/mastertrd/paper_diagnostics.py`
- Delete: `.github/workflows/oracle-deploy.yml`
- Delete: `.github/workflows/paper-status.yml`
- Delete: `tests/test_oracle_deployment.py`
- Delete: `tests/test_oracle_paper_status.py`
- Delete: `tests/test_oracle_paper_rotation_contract.py`
- Modify: `tests/test_paper_status.py`
- Modify: `tests/test_workflow_policy.py`
- Modify: `tests/test_local_scheduler.py`
- Modify: `tests/test_operations_docs.py`

**Interfaces:**
- Consumes: local `paper_status_payload`, local scheduler, `live_node`, runtime safety gates.
- Produces: no Oracle-specific executable/import/workflow path.

- [ ] **Step 1: Remove Oracle-only assertions from shared tests**

Keep tests for `paper_status_payload` itself. Remove only tests whose subject is `.github/workflows/paper-status.yml`, Oracle SSH/systemd behavior, or `.github/workflows/oracle-deploy.yml`. Update the local scheduler contract to check only workflows that still exist.

- [ ] **Step 2: Delete Oracle implementation/workflow/test files**

Use `git rm` for the files listed above. Do not remove `paper_status.py`, `live_node.py`, `runtime.py`, reconciliation, risk, testnet, or provider-admission modules.

- [ ] **Step 3: Run focused runtime/safety tests**

Run:
```bash
uv run pytest -q \
  tests/test_local_runtime_contract.py \
  tests/test_paper_status.py \
  tests/test_live_node.py \
  tests/test_runtime.py \
  tests/test_risk_runtime.py \
  tests/test_reconciliation.py \
  tests/test_workflow_policy.py \
  tests/test_local_scheduler.py
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove Oracle operator runtime"
```
### Task 3: Make active docs local-first

**Files:**
- Modify: `README.md`
- Modify: `MASTER_PLAN.md`
- Rewrite/simplify: `docs/OPERATIONS.md`
- Modify: `docs/THIN_CORE_PROGRESS.md`

**Interfaces:**
- Consumes: `mastertrd app`, `mastertrd scheduler`, `mastertrd.live_node`, existing runtime env gates.
- Produces: one current operational path for local PAPER/LIVE; historical Oracle docs stay archived under dated specs/plans.

- [ ] **Step 1: Add a failing active-doc contract**

Extend `tests/test_local_runtime_contract.py` so active docs must not instruct users to set `ORACLE_ENABLED`, dispatch Oracle Deploy, or use `oracle-deploy.yml`, while requiring local app/PAPER/LIVE safety terms.

- [ ] **Step 2: Run and confirm RED**

Run: `uv run pytest -q tests/test_local_runtime_contract.py`
Expected: FAIL on current active Oracle instructions.

- [ ] **Step 3: Simplify active documentation**

`README.md` presents one local start path. `MASTER_PLAN.md` changes the portable-node requirement from an Oracle adapter to a local portable execution node. `docs/OPERATIONS.md` becomes a concise local runbook covering install/start, PAPER, TESTNET, LIVE fail-closed gates, credentials, kill/restart/recovery, logs/artifacts, and backups. Do not weaken any LIVE safety gate.

- [ ] **Step 4: Verify docs + operations tests**

Run:
```bash
uv run pytest -q tests/test_local_runtime_contract.py tests/test_operations_docs.py tests/test_live_node.py tests/test_runtime.py
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md MASTER_PLAN.md docs/OPERATIONS.md docs/THIN_CORE_PROGRESS.md tests/test_local_runtime_contract.py tests/test_operations_docs.py
git commit -m "docs: make local runtime authoritative"
```
### Task 4: Prove cleanup and record the next slice

**Files:**
- Modify: `docs/THIN_CORE_PROGRESS.md`

**Interfaces:**
- Consumes: the local-only runtime tree after Tasks 1-3.
- Produces: exact regression/size evidence and the next consolidation target.

- [ ] **Step 1: Run complete verification**

```bash
uv lock --check
uv pip check
uv run pytest -q
```
Expected: zero failures.

- [ ] **Step 2: Measure the deletion**

Record source/test/workflow LOC before/after using `wc -l`, and confirm no active source/workflow imports Oracle modules with:

```bash
grep -RInE 'mastertrd\.oracle|oracle_paper_status|oracle-deploy.yml|ORACLE_ENABLED' src .github README.md MASTER_PLAN.md docs/OPERATIONS.md || true
```

- [ ] **Step 3: Update progress ledger**

Record commits, exact passing-test count, deleted LOC, and set the next incomplete slice to consolidation of duplicate PAPER/session/runtime wrappers behind one trading-service interface.

- [ ] **Step 4: Commit and push checkpoint**

```bash
git add docs/THIN_CORE_PROGRESS.md
git commit -m "docs: record local runtime cleanup evidence"
git push
```

## Self-review

This plan preserves the actual research/execution/risk path, removes only the proven dead Oracle/operator boundary, corrects the `asset_transfer.py` inventory classification, keeps historical provenance, and makes current product docs match the approved local-first architecture. No placeholders remain.
