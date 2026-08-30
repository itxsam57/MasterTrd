# MasterTrd Acceptance Evidence

This document maps the `MASTER_PLAN.md` definition of done to concrete repository evidence. A code path is not marked complete merely because it exists: automated claims require an executable test/workflow, and credential/host-dependent claims remain explicit external gates.

| Definition-of-done requirement | Repository evidence | Status |
| --- | --- | --- |
| Clean public clone/install | `pyproject.toml`, `uv.lock`, `.github/workflows/acceptance.yml` (`uv lock --check`, `uv sync --locked --all-extras`, `uv pip check`) | AUTOMATED_GATE |
| Pinned dependency lock | `uv.lock`; lock checks in `full-stack.yml`, `lockfile.yml`, `acceptance.yml` | AUTOMATED_GATE |
| Unit/contract/integration/regression suites | `tests/`, `tests/integration/`; cumulative `pytest -q` in acceptance | AUTOMATED_GATE |
| Historical-data import/integrity | `src/mastertrd/data/binance_public.py`, `src/mastertrd/nautilus_data.py`; data/integration tests | AUTOMATED_GATE |
| Strategy generation + deterministic genome hashing | `src/mastertrd/genome.py`, `src/mastertrd/research/generator.py`; genome/generator tests | AUTOMATED_GATE |
| VectorBT screen | research stack and `.github/workflows/research-stack.yml` | AUTOMATED_GATE |
| Optuna optimization | `src/mastertrd/research/optimize.py`; research integration tests | AUTOMATED_GATE |
| pymoo evolution | advanced research/generation integration tests | AUTOMATED_GATE |
| Nautilus backtest | `src/mastertrd/nautilus_backtest.py`; `tests/integration/test_nautilus_backtest.py` | AUTOMATED_GATE |
| Validation pipeline + hidden gate | `validation.py`, `robustness.py`, `hidden_gate.py`, related unit/integration tests | AUTOMATED_GATE |
| Specialist HFT gate | `hft_engine.py`, `hft_validation.py`, `research/hft_specialist.py`; HFTBacktest probes/stress suite | AUTOMATED_GATE |
| Research memory/reproducibility | `memory.py`, `memory_duckdb.py`, result/evidence hashes and DuckDB integration tests | AUTOMATED_GATE |
| Paper persistence/recovery | `paper_session.py`, `paper_archive.py`, paper persistence/recovery/safety tests | AUTOMATED_GATE |
| Venue DEMO/TESTNET smoke | Mode-specific credentials are required and must never be committed or pasted into project files | OWNER_INPUT_REQUIRED |
| Reconciliation + kill switches | `risk.py`, `governor.py`, live-readiness/execution-node tests | AUTOMATED_GATE |
| Secret/public-repo audit | `.github/workflows/security.yml` plus tracked-file guard in `acceptance.yml` | AUTOMATED_GATE |
| ARM64/Oracle deployment artifact | `deploy/oracle/`, `src/mastertrd/oracle.py`, `tests/test_oracle_deployment.py`, manual-only `oracle-deploy.yml` | AUTOMATED_ARTIFACT_GATE |
| Real Oracle-host smoke | Requires owner-provided host/user/SSH secret through GitHub Environment | OWNER_INPUT_REQUIRED |
| Cumulative green CI | `acceptance.yml` + existing subsystem workflows must be green at the same final commit SHA | FINAL_SHA_GATE |

## Purpose acceptance

The final automated acceptance workflow must prove all of the following at one commit:

1. The dependency lock is internally consistent and every admitted optional subsystem can coexist in one Python 3.13 environment.
2. The full unit/integration/regression suite passes from the locked environment.
3. `MASTERTRD_MODE=PAPER` with `LIVE_TRADING_ENABLED=false` reaches `PAPER_READY` without any Binance credential namespace.
4. PAPER cannot silently become an exchange execution path; exchange-node construction and LIVE activation remain covered by dedicated fail-closed tests.
5. Tracked repository content does not contain private-key blocks, seed/mnemonic material, populated password/token assignments, or accidentally tracked non-example `.env` files.
6. Oracle deployment remains manual-only, exact-SHA pinned, secret-backed, architecture-portable, and does not start the service or enable LIVE automatically.

## External acceptance boundary

The repository can be code-complete without exchange or host secrets. The following statements MUST NOT be claimed until their external evidence exists:

- “Binance DEMO credentials authenticated successfully.”
- “Binance TESTNET credentials authenticated successfully.”
- “Oracle host deployment completed successfully.”
- “LIVE trading executed successfully.”

When credentials become available, supply them only through GitHub/host secret mechanisms. Any first LIVE activation remains a separate owner-controlled operation with minimal size and the existing risk/kill-switch gates; it is not part of code-completion deployment.
