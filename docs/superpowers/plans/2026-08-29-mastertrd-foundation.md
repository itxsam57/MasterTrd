# MasterTrd Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a safe, deterministic core that every research/execution engine can plug into without bypassing validation or live-trading safety.

**Architecture:** Build dependency-light canonical contracts first, then deterministic genome hashing, promotion/risk governors, append-only research memory, and CI. External engines are admitted afterward through adapters and cumulative integration gates.

**Tech Stack:** Python 3.13, pytest; optional DuckDB/Parquet and research engines per `MASTER_PLAN.md`.

**Spec:** `MASTER_PLAN.md`

## Global Constraints

- NautilusTrader is the sole authoritative execution engine.
- `LIVE_TRADING_ENABLED=false` by default.
- No secrets or private live/account state in git.
- Only the Promotion Governor can advance strategy lifecycle state.
- Every result is reproducible by hashes and version metadata.
- External dependencies are stacked only after cumulative gates remain green.

---

### Task 1: Canonical contracts
**Files:** `src/mastertrd/contracts.py`, `tests/test_contracts.py`
- [x] Define runtime mode, strategy state, market bar and evaluation result contracts.
- [x] Reject malformed market bars and non-finite result metrics.
- [x] Test valid/invalid construction.

### Task 2: Strategy genome
**Files:** `src/mastertrd/genome.py`, `tests/test_genome.py`
- [x] Represent strategy rules as canonical data.
- [x] Compute deterministic SHA-256 hash independent of mapping insertion order.
- [x] Test hash determinism and semantic changes.

### Task 3: Promotion governor
**Files:** `src/mastertrd/governor.py`, `tests/test_governor.py`
- [x] Encode legal lifecycle transitions.
- [x] Require named evidence gates for advancement.
- [x] Fail closed on missing evidence or illegal jumps.

### Task 4: Runtime/risk safety
**Files:** `src/mastertrd/runtime.py`, `src/mastertrd/risk.py`, `tests/test_runtime.py`, `tests/test_risk.py`
- [x] Parse mode/env configuration with live fail-closed behavior.
- [x] Provide independent exposure/daily-loss/drawdown/order-rate checks.
- [x] Test kill-switch decisions.

### Task 5: Research memory
**Files:** `src/mastertrd/memory.py`, `tests/test_memory.py`
- [x] Store append-only JSONL research records using opaque hashes.
- [x] Reject records whose declared genome hash does not match the genome.
- [x] Test round-trip and tamper rejection.

### Task 6: CI/public-repo gate
**Files:** `.github/workflows/ci.yml`, `.github/workflows/security.yml`
- [x] Run Python 3.13 tests on every push/PR.
- [x] Run secret-pattern and dependency audit gates.

### Task 7: External engine adapters
- [ ] Add MarketDataContract adapters for Parquet/DuckDB.
- [ ] Add VectorBT screening adapter and parity fixtures.
- [ ] Add Optuna and pymoo research adapters.
- [ ] Add statsmodels/arch/ruptures/River/skfolio/QuantStats specialist gates.
- [ ] Add Nautilus authoritative backtest/execution adapter.
- [ ] Add hftbacktest specialist validator.

### Task 8: Venue/runtime deployment
- [ ] Add Binance public-data ingestion with checksums.
- [ ] Add Binance demo/testnet smoke workflow driven by GitHub Secrets.
- [ ] Add local LiveNode service and reconciliation recovery.
- [ ] Add disabled-by-default Oracle ARM64 adapter and deployment package.

### Task 9: Final cumulative acceptance
- [ ] Run clean-install, contract, research, backtest, paper persistence, secret scan, kill switch, ARM64 build and venue smoke gates.
- [ ] Produce an acceptance report tied to exact commit SHA.
