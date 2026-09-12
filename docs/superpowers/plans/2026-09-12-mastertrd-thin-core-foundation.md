# MasterTrd Thin-Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first working local consumer control plane: one `mastertrd` command, one local Streamlit app, isolated local research workers, a durable progress ledger, and no required hosted scheduler.

**Architecture:** Keep the existing strategy, research, risk, PAPER, and Nautilus engines intact. Add a thin application-service layer and local process launcher around those engines; the UI contains no trading logic. This plan intentionally does not delete runtime modules yet—deletion starts only after the replacement path has passing parity evidence.

**Tech Stack:** Python 3.13, Streamlit, existing DuckDB/Parquet, VectorBT/Optuna/pymoo, NautilusTrader, pytest, subprocess-based local workers.

**Spec:** `docs/superpowers/specs/2026-09-12-mastertrd-thin-core-local-first-design.md`

## Global Constraints

- No mandatory Vercel, PostHog, Neon, Oracle, or GitHub-hosted Actions dependency.
- Preserve fail-closed LIVE gates and all existing risk/reconciliation semantics.
- Heavy research must run outside the UI/trading process.
- Keep the full strategy universe visible; readiness/blockers remain explicit.
- No artificial MasterTrd limit on strategy count, assets, tests, or parameter sweeps.
- Preserve all existing 730 passing tests while adding focused tests.
- Existing ORB working-tree changes are out of scope and must not be mixed into this branch.

---

### Task 1: Durable progress ledger and cleanup inventory

**Files:**
- Create: `docs/THIN_CORE_PROGRESS.md`
- Create: `docs/THIN_CORE_INVENTORY.md`
- Test: `tests/test_thin_core_docs.py`

**Interfaces:**
- Consumes: approved thin-core spec.
- Produces: a machine-readable-enough progress contract and explicit KEEP/MERGE/REPLACE/DELETE inventory used by later cleanup plans.

- [ ] **Step 1: Write the failing docs contract test**

```python
from pathlib import Path


def test_thin_core_progress_and_inventory_exist():
    progress = Path("docs/THIN_CORE_PROGRESS.md").read_text()
    inventory = Path("docs/THIN_CORE_INVENTORY.md").read_text()
    assert "Thin Core / Full Lab / One Local App" in progress
    assert "Current slice" in progress and "Next incomplete slice" in progress
    for token in ("KEEP", "MERGE", "REPLACE", "DELETE"):
        assert token in inventory
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `uv run pytest tests/test_thin_core_docs.py -q`
Expected: FAIL because both docs do not exist.

- [ ] **Step 3: Add the ledger and inventory**

The progress file records baseline SHA, current slice, completed slices, next slice, blockers, PAPER readiness, LIVE readiness, and evidence commands. The inventory classifies every top-level `src/mastertrd/*.py` module and every `.github/workflows/*.yml` file with one short reason.

- [ ] **Step 4: Run the test and confirm GREEN**

Run: `uv run pytest tests/test_thin_core_docs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/THIN_CORE_PROGRESS.md docs/THIN_CORE_INVENTORY.md tests/test_thin_core_docs.py
git commit -m "docs: add thin-core progress and cleanup inventory"
```

### Task 2: One consumer command and application service

**Files:**
- Create: `src/mastertrd/app_service.py`
- Create: `src/mastertrd/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_app_service.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `AppService.snapshot()`, `AppService.strategy_rows()`, and `mastertrd` console command.
- `strategy_rows()` returns plain dictionaries with `recipe_id`, `name`, `family`, `readiness`, `assets`, `horizons`, and `blocker` so UI code has no strategy-domain logic.

- [ ] **Step 1: Write failing service tests**

```python
from mastertrd.app_service import AppService


def test_app_service_exposes_full_strategy_catalog():
    rows = AppService().strategy_rows()
    assert len(rows) >= 189
    assert {"recipe_id", "name", "readiness", "blocker"} <= rows[0].keys()


def test_snapshot_is_safe_by_default(monkeypatch):
    monkeypatch.delenv("MASTERTRD_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    snapshot = AppService().snapshot()
    assert snapshot["mode"] == "PAPER"
    assert snapshot["live_enabled"] is False
```

- [ ] **Step 2: Run tests and confirm RED**
Run: `uv run pytest tests/test_app_service.py -q`
Expected: FAIL because `app_service` does not exist.

- [ ] **Step 3: Implement the thin service**
Use only `RuntimeConfig.from_env`, `STRATEGY_RECIPES`, and readiness enums; do not duplicate strategy or risk rules.

- [ ] **Step 4: Add the `mastertrd` console entrypoint**
Add `[project.scripts] mastertrd = "mastertrd.cli:main"`. Implement `mastertrd status`, `mastertrd strategies`, while the `app` subcommand is added only in Task 4 when Streamlit is fully wired.

- [ ] **Step 5: Verify GREEN**
Run: `uv run pytest tests/test_app_service.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add src/mastertrd/app_service.py src/mastertrd/cli.py pyproject.toml tests/test_app_service.py tests/test_cli.py uv.lock
git commit -m "feat: add thin local control command"
```

### Task 3: Isolated local research jobs

**Files:**
- Create: `src/mastertrd/local_jobs.py`
- Create: `src/mastertrd/local_job_worker.py`
- Modify: `src/mastertrd/app_service.py`
- Modify: `src/mastertrd/cli.py`
- Test: `tests/test_local_jobs.py`

**Interfaces:**
- Produces: `launch_research_job(recipe_id: str, root: Path) -> LocalJobReceipt` and `list_local_jobs(root: Path) -> list[LocalJobReceipt]`.
- Job receipts live under `artifacts/local-jobs/<job_id>/receipt.json`; research outputs stay under that job directory and continue using the existing research engine/storage.

- [ ] **Step 1: Write failing lifecycle tests**

```python
from pathlib import Path
from mastertrd.local_jobs import launch_research_job, list_local_jobs


def test_launch_research_job_uses_separate_process(tmp_path, monkeypatch):
    launched = {}
    monkeypatch.setattr("mastertrd.local_jobs.subprocess.Popen", lambda argv, **kw: launched.update(argv=argv, kw=kw) or type("P", (), {"pid": 1234})())
    receipt = launch_research_job("ema-cross-fast", tmp_path)
    assert receipt.pid == 1234
    assert "mastertrd.local_job_worker" in launched["argv"]
    assert launched["kw"]["start_new_session"] is True
    assert list_local_jobs(tmp_path)[0].recipe_id == "ema-cross-fast"
```

- [ ] **Step 2: Run and confirm RED**
Run: `uv run pytest tests/test_local_jobs.py -q`
Expected: FAIL because the local job module does not exist.

- [ ] **Step 3: Implement receipt + launcher + worker**
Use `subprocess.Popen` without a shell. The worker sets `MASTERTRD_RESEARCH_RECIPE_ID`, `MASTERTRD_RESEARCH_ARTIFACT_DIR`, and `MASTERTRD_CODE_HASH`, calls the existing `research_job.main()`, writes structured stdout/stderr logs, and atomically updates receipt status to `SUCCEEDED` or `FAILED`.

- [ ] **Step 4: Add CLI access**
`mastertrd backtest --recipe ema-cross-fast` launches one local job and prints its job id/path. `mastertrd jobs` lists receipts; no hosted service is involved.

- [ ] **Step 5: Verify GREEN**
Run: `uv run pytest tests/test_local_jobs.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add src/mastertrd/local_jobs.py src/mastertrd/local_job_worker.py src/mastertrd/app_service.py src/mastertrd/cli.py tests/test_local_jobs.py tests/test_cli.py
git commit -m "feat: run research as isolated local jobs"
```

### Task 4: Local Streamlit consumer app

**Files:**
- Create: `src/mastertrd/local_app.py`
- Modify: `src/mastertrd/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_local_app_contract.py`

**Interfaces:**
- Consumes only `AppService` and local job APIs.
- Produces: `mastertrd app`, which starts Streamlit locally and exposes Dashboard, Strategies, Backtest Lab, Trading, Accounts / Providers, and System Health views.

- [ ] **Step 1: Write failing UI contract test**
```python
from pathlib import Path


def test_local_app_has_consumer_sections():
    text = Path("src/mastertrd/local_app.py").read_text()
    for title in ("Dashboard", "Strategies", "Backtest Lab", "Trading", "Accounts / Providers", "System Health"):
        assert title in text
```

- [ ] **Step 2: Run and confirm RED**
Run: `uv run pytest tests/test_local_app_contract.py -q`
Expected: FAIL because the file does not exist.

- [ ] **Step 3: Add Streamlit as an app extra and implement the UI**
Add `app = ["streamlit>=1.40,<2"]`. Keep UI code declarative: render service output, submit local jobs, show job/results paths, and show LIVE as locked unless `RuntimeConfig` is actually LIVE-enabled.

- [ ] **Step 4: Wire `mastertrd app`**
Launch `python -m streamlit run <local_app.py>` using `subprocess.run` without shell expansion.

- [ ] **Step 5: Verify GREEN**
Run: `uv lock && uv sync --locked --all-extras && uv run pytest tests/test_local_app_contract.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add src/mastertrd/local_app.py src/mastertrd/cli.py pyproject.toml uv.lock tests/test_local_app_contract.py tests/test_cli.py
git commit -m "feat: add one local MasterTrd app"
```

### Task 5: Remove required hosted schedules

**Files:**
- Modify: `.github/workflows/autonomous-research.yml`
- Modify: `.github/workflows/paper-status.yml`
- Modify: `.github/workflows/public-binance-canary.yml`
- Create: `src/mastertrd/local_scheduler.py`
- Modify: `src/mastertrd/cli.py`
- Test: `tests/test_local_scheduler.py`
- Test: `tests/test_workflow_policy.py`

**Interfaces:**
- Produces: `mastertrd scheduler`, a local long-running scheduler for lightweight canary/research triggers.
- GitHub workflows remain manually dispatchable/CI-safe but lose recurring `schedule:` triggers so hosted minutes are never required for normal operation.

- [ ] **Step 1: Write failing scheduler/policy tests**
```python
from pathlib import Path


def test_consumer_runtime_has_no_required_hosted_cron():
    for name in ("autonomous-research.yml", "paper-status.yml", "public-binance-canary.yml"):
        text = Path(".github/workflows", name).read_text()
        assert "  schedule:" not in text


def test_local_scheduler_defines_canary_and_research_tasks():
    from mastertrd.local_scheduler import default_tasks
    names = {task.name for task in default_tasks()}
    assert {"public-canary", "research"} <= names
```

- [ ] **Step 2: Run and confirm RED**
Run: `uv run pytest tests/test_local_scheduler.py tests/test_workflow_policy.py -q`
Expected: FAIL because hosted schedules still exist and local scheduler is absent.

- [ ] **Step 3: Implement minimal local scheduler**
Use only stdlib time/subprocess. Schedule public canary every 6 hours and research weekly; do not duplicate PAPER polling because the local app reads local runtime status directly.

- [ ] **Step 4: Remove only recurring schedule blocks from the three workflows**
Keep `workflow_dispatch` and push-triggered verification intact.

- [ ] **Step 5: Verify GREEN**
Run: `uv run pytest tests/test_local_scheduler.py tests/test_workflow_policy.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add src/mastertrd/local_scheduler.py src/mastertrd/cli.py .github/workflows/autonomous-research.yml .github/workflows/paper-status.yml .github/workflows/public-binance-canary.yml tests/test_local_scheduler.py tests/test_workflow_policy.py
git commit -m "refactor: move recurring jobs to local scheduler"
```

### Task 6: One-command release smoke and progress update

**Files:**
- Modify: `README.md`
- Modify: `docs/THIN_CORE_PROGRESS.md`
- Create: `tests/test_consumer_local_smoke.py`

**Interfaces:**
- Verifies the user-facing contract: `mastertrd status`, `mastertrd strategies`, `mastertrd jobs`, and `mastertrd app --help` resolve from one installed package.

- [ ] **Step 1: Write failing consumer smoke test**
```python
import subprocess


def test_consumer_commands_are_available():
    for args in (["status"], ["strategies"], ["jobs"], ["app", "--help"]):
        result = subprocess.run(["mastertrd", *args], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run the smoke test**
Run: `uv run pytest tests/test_consumer_local_smoke.py -q`
Expected before final wiring: FAIL; after Tasks 2-5: PASS.

- [ ] **Step 3: Update README and progress ledger**
Document `uv sync --all-extras`, `mastertrd app`, local artifact locations, PAPER/LIVE lock behavior, and the next slice: trading-worker consolidation + wrapper deletion.

- [ ] **Step 4: Run focused foundation suite**
Run: `uv run pytest tests/test_thin_core_docs.py tests/test_app_service.py tests/test_cli.py tests/test_local_jobs.py tests/test_local_app_contract.py tests/test_local_scheduler.py tests/test_workflow_policy.py tests/test_consumer_local_smoke.py -q`
Expected: PASS.

- [ ] **Step 5: Run full regression**
Run: `uv run pytest -q`
Expected: all existing 730 tests plus new tests pass.

- [ ] **Step 6: Verify clean dependency/runtime state**
Run: `uv lock --check && uv pip check && git status --short && git diff --check`
Expected: lock valid, dependency check clean, only intended plan/progress changes before commit, no whitespace errors.

- [ ] **Step 7: Commit**
```bash
git add README.md docs/THIN_CORE_PROGRESS.md tests/test_consumer_local_smoke.py
git commit -m "docs: finish local thin-core foundation slice"
```

## Next plans after this foundation

1. Trading-worker consolidation: one PAPER/LIVE controller around existing Nautilus execution paths.
2. Local portfolio/multi-strategy control: account -> portfolio -> strategies with shared risk.
3. Cleanup deletion pass: remove superseded PAPER/Oracle/status/runtime wrappers only after parity tests.
4. Consumer hardening: restart/recovery, emergency stop UI, provider/account setup, release packaging.
5. Provider-specific LIVE admission: at least one real-market provider must pass all safety receipts before LIVE unlocks.