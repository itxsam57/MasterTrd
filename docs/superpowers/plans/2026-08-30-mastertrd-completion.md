# MasterTrd Completion Plan

**Date:** 2026-08-30  
**Branch:** `completion/2026-08-30`  
**Base SHA:** `2386d9076f4e4ba2db0914d90bc850a4056aaa2a`  
**Source of truth:** `MASTER_PLAN.md`

## Goal

Close the remaining definition-of-done gaps without weakening any promotion, risk, secret-isolation, or live-trading safeguards. `main` remains untouched until the isolated branch is fully verified.

## Baseline already verified

- Main CI and security workflows are green at the base SHA.
- Locked dependency stack exists in `uv.lock` and full-stack CI installs all extras from the lock and runs the cumulative suite.
- Research generation, VectorBT/Optuna/pymoo, Nautilus backtest/sandbox probes, hidden/robustness/transfer gates, paper persistence, risk/promotion governors, and public-repo safety tests exist.
- Runtime defaults are `PAPER`, `LIVE_TRADING_ENABLED=false`, `ORACLE_ENABLED=false`.

## Gap 1 — Persistent authoritative execution node

Current `src/mastertrd/live_node.py` only performs preflight checks and emits heartbeats. It does not construct/run the authoritative NautilusTrader persistent execution node.

### TDD steps

1. Add `tests/test_live_execution_node.py` specifying:
   - PAPER stays isolated from exchange credentials and cannot accidentally create a live Binance node.
   - DEMO/TESTNET/LIVE create a Nautilus Binance node configuration only after credential/runtime validation.
   - LIVE is rejected unless both `MASTERTRD_MODE=LIVE` and `LIVE_TRADING_ENABLED=true` are present.
   - Node lifecycle always disposes resources after stop/failure.
   - No withdrawal capability or fallback-to-live path exists.
2. Push the test alone and record a RED GitHub Actions result.
3. Implement the smallest production runtime bridge in `src/mastertrd/live_node.py` / a focused helper module, reusing `build_nautilus_binance_configs` and the locked Nautilus version.
4. Extend `.github/workflows/execution-stack.yml` path coverage and execution tests for the persistent node.
5. Push and require GREEN execution + cumulative CI.

## Gap 2 — Portable Oracle/Linux ARM64 deployment artifact

`src/mastertrd/oracle.py` renders fragments, but the repository lacks a deployable artifact/workflow.

### TDD steps

1. Extend `tests/test_oracle_deployment.py` to require committed deployment assets:
   - `deploy/oracle/bootstrap.sh`
   - `deploy/oracle/mastertrd.service`
   - `deploy/oracle/mastertrd-health`
   - `deploy/oracle/mastertrd.logrotate`
   - `deploy/oracle/mastertrd.env.example`
   - `.github/workflows/oracle-deploy.yml`
2. Require bootstrap to support Linux ARM64/Ampere A1 and x86_64, install from an exact git ref, create a dedicated service account/venv/state/log dirs, preserve secrets outside git, and never auto-enable LIVE.
3. Require systemd restart/recovery, health check, log rotation, protected environment loading and writable state/log locations.
4. Require deployment workflow to be manual-only and secret-backed; no embedded hostname/user/key and no automatic live activation.
5. Push tests first for RED, then add assets and push for GREEN.

## Gap 3 — Final clean-clone / purpose acceptance

1. Add/update `README.md` with exact safe install/run/deploy commands and accurate implementation status.
2. Add `docs/ACCEPTANCE.md` mapping every `MASTER_PLAN.md` definition-of-done item to concrete code/tests/workflows and explicitly mark credential-dependent venue smoke tests as `OWNER_INPUT_REQUIRED`, not falsely passed.
3. Add `.github/workflows/acceptance.yml` that on push/PR:
   - checks `uv lock --check`;
   - performs `uv sync --locked --all-extras`;
   - runs `uv pip check`;
   - runs the cumulative pytest suite;
   - runs a safe PAPER preflight/purpose smoke;
   - scans tracked files for forbidden credential material.
4. Verify all branch workflows at one exact final SHA.
5. Perform code-review pass and address findings.
6. Merge only after verification; live capital remains disabled until owner supplies exchange/host secrets and explicitly activates minimal-size live mode.

## Completion boundary

The repository can be code-complete without owner credentials. Real Binance DEMO/TESTNET and Oracle-host smoke tests cannot be honestly marked passed until those external secrets/host details exist. Those are the only allowed external blockers; they must remain fail-closed and documented.