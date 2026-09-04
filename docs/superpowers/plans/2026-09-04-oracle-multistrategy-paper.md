# Oracle Multi-Strategy Minute-Scale PAPER Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy every exact-SHA ResearchJob PAPER candidate as an isolated Oracle PAPER process with 10-minute evidence windows and aggregate read-only status.

**Architecture:** Extend the existing identity-bound Oracle deployment from one candidate to a validated candidate set. Materialize one environment/state root per candidate and run each with a systemd template instance while preserving the repository-owned `mastertrd.live_node`, risk runtime, reconciliation, bar completeness, and kill semantics. Add an aggregate status reader over isolated session journals.

**Tech Stack:** Python 3.13, pytest, NautilusTrader 1.231, GitHub Actions YAML, systemd, Bash, Oracle Linux/Ubuntu host adapter.

**Spec:** `docs/superpowers/specs/2026-09-04-oracle-multistrategy-paper-design.md`

## Global Constraints

- All Oracle strategy instances use `MASTERTRD_MODE=PAPER` and `LIVE_TRADING_ENABLED=false`.
- Candidate manifests must match the deployed `GITHUB_SHA` and current `uv.lock` hash before SSH mutation.
- Candidate/session/archive/history/rotation files must be isolated per genome.
- Evidence rotation is exactly 600 seconds; strategy signal timeframes are never rewritten to fabricate activity.
- No PAPER result counts as TESTNET/LIVE evidence or bypasses the Promotion Governor.
- Existing Oracle LIVE-mutation refusal, SSH pinning, locked dependency checks, risk, reconciliation, kill, and crash recovery remain unchanged.

---
### Task 1: Atomic PAPER candidate-set validation

**Files:**
- Modify: `src/mastertrd/oracle.py`
- Modify: `tests/test_oracle_deployment.py`

**Interfaces:**
- Produces: `validate_paper_candidate_manifests(payloads, *, expected_code_hash, expected_lock_hash) -> tuple[StrategyGenome, ...]`
- Guarantees: non-empty list, every single manifest passes existing validation, and strategy/genome identities are unique.

- [ ] **Step 1: Write failing tests** for two valid candidates, empty/non-list input, stale code/lock identity, and duplicate strategy/genome identity.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_oracle_deployment.py -k 'candidate_manifest'` and confirm RED on the missing set validator.
- [ ] **Step 3: Implement minimal set validator** by reusing `validate_paper_candidate_manifest`; do not weaken single-manifest checks.
- [ ] **Step 4: Re-run focused tests** and confirm GREEN.
- [ ] **Step 5: Commit** `feat: validate Oracle PAPER candidate sets`.

### Task 2: Multi-instance Oracle service contract

**Files:**
- Modify: `src/mastertrd/oracle.py`
- Modify: `tests/test_oracle_deployment.py`

**Interfaces:**
- Produces: systemd template `mastertrd-paper@.service` reading `/etc/mastertrd/paper/%i.env`.
- Produces: health script capable of checking one named PAPER instance.
- Preserves: legacy `mastertrd.service` rendering only where needed for compatibility tests; Oracle Deploy uses the new PAPER template.

- [ ] **Step 1: Write failing rendering tests** asserting per-instance environment isolation, restart policy, filesystem protections, and `mastertrd.live_node` execution.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_oracle_deployment.py -k 'systemd or bootstrap'` and confirm RED.
- [ ] **Step 3: Implement template/unit/bootstrap rendering** with `/var/lib/mastertrd`, `/etc/mastertrd/paper`, and no embedded credentials.
- [ ] **Step 4: Re-run focused tests** and confirm GREEN.
- [ ] **Step 5: Commit** `feat: add isolated Oracle PAPER service instances`.
### Task 3: Transactional multi-candidate Oracle Deploy

**Files:**
- Modify: `.github/workflows/oracle-deploy.yml`
- Modify: `tests/test_oracle_deployment.py`
- Modify: `tests/test_workflow_policy.py`

**Interfaces:**
- Workflow input: `paper_candidates_json`, a JSON array of public-safe ResearchJob PAPER manifests.
- Host paths: `/var/lib/mastertrd/paper/<sha>/<genome_hash>/...` and `/etc/mastertrd/paper/<instance>.env`.
- Instance name: a deterministic safe identifier derived from the genome hash; never raw user-controlled shell text.

- [ ] **Step 1: Write failing workflow-contract tests** requiring candidate-array input, full pre-SSH validation, 600-second rotation, instance env files, systemd template start/health checks, and LIVE mutation refusal.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_oracle_deployment.py tests/test_workflow_policy.py` and confirm RED.
- [ ] **Step 3: Change validation step** to parse the array, validate all candidates atomically, write canonical candidate files plus a sanitized deployment index, and export only deterministic identifiers.
- [ ] **Step 4: Change remote deployment** to materialize every isolated root/env, set `MASTERTRD_PAPER_ROTATE_AFTER_SECONDS=600`, disable legacy single PAPER service, then start and health-check every requested `mastertrd-paper@<instance>.service`.
- [ ] **Step 5: Ensure stale PAPER instances are stopped only after new manifests and exact SHA are validated**, while LIVE-enabled hosts still fail before mutation.
- [ ] **Step 6: Re-run workflow tests** and confirm GREEN.
- [ ] **Step 7: Commit** `feat: deploy Oracle PAPER candidate matrix`.

### Task 4: Aggregate Oracle PAPER status

**Files:**
- Create: `src/mastertrd/oracle_paper_status.py`
- Create: `tests/test_oracle_paper_status.py`
- Modify: `.github/workflows/paper-status.yml`
- Modify: `tests/test_workflow_policy.py`

**Interfaces:**
- `oracle_paper_status_payload(root: Path, *, observed_ns: int) -> dict[str, object]` scans only direct genome/session roots and delegates each journal to `paper_status_payload`.
- Output contains exact deployed SHA plus a stable `strategies` list; no raw journals, credentials, balances, or private exchange payloads.

- [ ] **Step 1: Write failing unit tests** using two isolated session stores and assert identities/trades/telemetry stay separate.
- [ ] **Step 2: Run** `uv run pytest -q tests/test_oracle_paper_status.py` and confirm RED because the module does not exist.
- [ ] **Step 3: Implement the aggregate reader** with deterministic ordering and fail-closed handling for corrupt/mismatched session identity.
- [ ] **Step 4: Update PAPER Status workflow** to verify remote SHA, run the aggregate reader against `/var/lib/mastertrd/paper/<sha>`, enumerate `mastertrd-paper@*.service` health/restarts, and upload one sanitized aggregate artifact.
- [ ] **Step 5: Re-run status/workflow tests** and confirm GREEN.
- [ ] **Step 6: Commit** `feat: aggregate Oracle PAPER strategy status`.
### Task 5: Documentation, regression gates, push, and Oracle launch

**Files:**
- Modify: `docs/OPERATIONS.md`
- Modify as needed: tests touched above only for genuine regressions.

**Interfaces:**
- Operations runbook documents multi-instance PAPER paths, 600-second evidence rotation, aggregate status, rollback, and the invariant that Oracle Deploy is never a LIVE start mechanism.

- [ ] **Step 1: Update operations documentation** with `paper_candidates_json`, systemd instance names, 10-minute evidence windows, aggregate status, and safe stop/rollback commands.
- [ ] **Step 2: Run focused Oracle/PAPER suite:** `uv run pytest -q tests/test_oracle_deployment.py tests/test_oracle_paper_status.py tests/integration/test_oracle_paper_production.py tests/test_oracle_paper_rotation_contract.py tests/test_paper_status.py tests/test_workflow_policy.py`.
- [ ] **Step 3: Run execution/risk gates:** `uv run pytest -q tests/integration/test_paper_execution_canary_runtime.py tests/integration/test_risk_execution_hook.py tests/integration/test_reconciliation_evidence.py tests/integration/test_kill_switch_evidence.py`.
- [ ] **Step 4: Run full locked verification:** `uv lock --check && uv pip check && uv run pytest -q --cov=mastertrd --cov-branch --cov-fail-under=90`.
- [ ] **Step 5: Run repository security checks** with the project environment and `git diff --check`; do not lower thresholds or omit new code.
- [ ] **Step 6: Commit final docs/fixes**, verify clean tree, and push `feat/oracle-multistrategy-paper-20260904`.
- [ ] **Step 7: Verify exact-SHA GitHub CI/acceptance/security checks** all complete successfully.
- [ ] **Step 8: Obtain the current exact-SHA ResearchJob `paper_candidates` artifact**; if none exists, run the repository's current minute-scale research handoff rather than inventing manifests.
- [ ] **Step 9: Dispatch Oracle Deploy** with the exact candidate array, then collect aggregate PAPER status and verify every requested service is active, `LIVE_TRADING_ENABLED=false`, and each strategy has an isolated session.

## Self-review

The plan covers atomic identity validation, isolated multi-process execution, 600-second evidence windows, aggregate observability, LIVE refusal, regression/security gates, exact-SHA push, and actual Oracle deployment. It introduces no new execution engine or alternate risk path. No placeholder implementation steps remain.
