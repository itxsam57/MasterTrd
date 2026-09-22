# MasterTrd Thin-Core Ownership Inventory

This is the final compact ownership map. There are no open migration targets.

| State | Surface | Decision |
| --- | --- | --- |
| **KEEP** | `TradingService`, runtime factory, execution runtime, Nautilus adapters | One public trading boundary over proven execution primitives. |
| **KEEP** | ResearchBrain, robustness/hidden/specialist validation, DuckDB/Parquet | Canonical research lab and durable research state. |
| **KEEP** | Risk runtime/state, reconciliation, Governor, PAPER archive/lifecycle | Independent safety and lifecycle boundaries. |
| **KEEP** | StrategyGenome, strategy universe, provider capability matrix | Canonical strategy/provider contracts. |
| **KEEP** | `paper_portfolio.py` | Minimal shared-account PAPER orchestration; no second execution engine. |
| **KEEP** | `live_node.py` | Tiny compatibility entrypoint only; `mastertrd trading` is canonical. |
| **KEEP** | Optional CI/security/full-stack/testnet workflows | Verification only; never required for local runtime. |
| **MERGE** | None open | Previous app/status/operator overlap is already behind `TradingService`. |
| **REPLACE** | Hosted cron/operator status | Replaced by local scheduler, app status, and shared trading service. |
| **REPLACE** | Legacy cloud runtime/deploy product path | Replaced by portable local Linux/Windows runtime. |
| **DELETE** | `AppService`, standalone PAPER status/diagnostics, legacy cloud runtime/workflows | Removed after parity tests. |
| **DELETE** | custom `PaperLedger` | Removed; Nautilus owns authoritative PAPER accounting. |
| **DELETE** | JSONL research memory | Removed; DuckDB is canonical. |
| **DELETE** | one-off generated research-cycle wrapper | Removed; ResearchBrain owns the cycle. |
| **DELETE** | duplicate dependency registry/admission version matrix | Removed; `pyproject.toml` + `uv.lock` + locked full-stack acceptance are authoritative. |

## Invariants

- NautilusTrader is the only authoritative execution engine.
- PAPER is the default and needs no exchange execution credentials.
- LIVE cannot be enabled from the app.
- Research workers cannot own or block the persistent trading worker.
- Multiple PAPER strategies share one account/risk path.
- Only validated PAPER finalist manifests can be assembled by the app into a shared
  portfolio, and code/lock identity must match the current runtime.
- Secrets never enter repository state, app settings, research reports, or portfolio
  manifests.
