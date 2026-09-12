# MasterTrd Thin-Core Cleanup Inventory

This is a migration map, not a deletion command. **DELETE** means delete only after call-site audit and replacement/parity evidence. Safety, risk, reconciliation, and provider-admission behavior must remain fail-closed.

| Path | Action | Reason |
|---|---|---|
| `src/mastertrd/__init__.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/acceptance.py` | **REPLACE** | Replace operator/cloud-specific wrapper with local app/service/scheduler path while preserving core behavior. |
| `src/mastertrd/advanced_validation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/asset_transfer.py` | **DELETE** | Remove if confirmed unused after call-site/parity check; not part of consumer runtime. |
| `src/mastertrd/bar_completeness.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/binance_stream.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/capability_matrix.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/champion.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/contracts.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/credentials.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/dependencies.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/execution.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/execution_policy.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/execution_runtime.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/execution_signals.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/forward_scheduler.py` | **REPLACE** | Replace operator/cloud-specific wrapper with local app/service/scheduler path while preserving core behavior. |
| `src/mastertrd/genome.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/governor.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/hft_engine.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/hft_strategy.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/hft_validation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/hidden_cycle.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/hidden_gate.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/holdout.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/live_evidence.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/live_node.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/live_readiness.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/market_capabilities.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/memory.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/memory_duckdb.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/multi_leg_validation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_backtest.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_bar_strategy.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_binance.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_data.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_evaluation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_multileg_strategy.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_options_strategy.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/nautilus_paper.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/nautilus_risk_hook.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/nautilus_strategy.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/options_validation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/oracle.py` | **REPLACE** | Replace operator/cloud-specific wrapper with local app/service/scheduler path while preserving core behavior. |
| `src/mastertrd/oracle_paper_status.py` | **REPLACE** | Replace operator/cloud-specific wrapper with local app/service/scheduler path while preserving core behavior. |
| `src/mastertrd/paper.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_archive.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_challenger.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_cycle.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_diagnostics.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_events.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_evidence.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_execution_canary.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_forward.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_hardening.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_session.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/paper_status.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/product_contracts.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/public_market_canary.py` | **REPLACE** | Replace operator/cloud-specific wrapper with local app/service/scheduler path while preserving core behavior. |
| `src/mastertrd/reconciliation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/research_brain.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/research_candidate_generation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/research_cycle.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/research_job.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/risk.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/risk_profiles.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/risk_runtime.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/risk_state.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/robustness.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/robustness_cycle.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/runtime.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/runtime_factory.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/specialist_orchestrator.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/strategy_families.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/strategy_universe.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/streaming.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/testnet_candidate.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/testnet_smoke.py` | **MERGE** | Consolidate overlapping orchestration/state wrappers behind one research or trading service boundary. |
| `src/mastertrd/validation.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `src/mastertrd/venue.py` | **KEEP** | Core strategy, data, validation, execution semantics, provider capability, or safety primitive. |
| `.github/workflows/acceptance.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/autonomous-research.yml` | **REPLACE** | Keep optional/manual verification where useful; remove runtime dependence and recurring hosted scheduling. |
| `.github/workflows/ci.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/consumer-release-smoke.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/dependency-admission.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/execution-stack.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/full-stack.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/lockfile.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/oracle-deploy.yml` | **REPLACE** | Keep optional/manual verification where useful; remove runtime dependence and recurring hosted scheduling. |
| `.github/workflows/paper-status.yml` | **REPLACE** | Keep optional/manual verification where useful; remove runtime dependence and recurring hosted scheduling. |
| `.github/workflows/public-binance-canary.yml` | **REPLACE** | Keep optional/manual verification where useful; remove runtime dependence and recurring hosted scheduling. |
| `.github/workflows/research-stack.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/security.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
| `.github/workflows/testnet-smoke.yml` | **KEEP** | Optional CI/security/release verification; not required for local runtime. |
