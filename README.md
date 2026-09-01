# MasterTrd

Autonomous quantitative research, validation, paper/demo/testnet, and controlled live-trading platform.

`MASTER_PLAN.md` is the canonical specification.

## Safety defaults

- `LIVE_TRADING_ENABLED=false`
- No exchange secrets belong in git.
- Trading keys must have **no withdrawal permission**.
- No strategy can become live-eligible without the Promotion Governor.

## Current implementation status

**Implementation status: PROCESS_READY.** The repository-owned research, PAPER, DEMO/TESTNET, risk, recovery, specialist, and evidence paths in `docs/superpowers/plans/2026-08-31-mastertrd-v2-plan-closure.md` are implemented and covered by cumulative acceptance; owner-controlled external receipts are tracked separately in `docs/ACCEPTANCE_REPORT.md`.

The checked-in acceptance snapshot records verified historical-data ingestion, family-aware execution compilation, research screening/optimization/evolution, specialist statistical/regime/portfolio validation, the autonomous research brain, execution-risk wiring, persistent paper/demo/testnet runtime and recovery, real L2/HFT validation, live-readiness evidence production, autonomous workflows, Oracle/local deployment packaging, and exact-SHA acceptance.

Process readiness is deliberately separate from LIVE activation. The real `testnet_smoke` evidence is currently `BLOCKED_OWNER_INPUT` until approved Binance TESTNET credentials/account identity are supplied through the protected `testnet` environment. Therefore LIVE remains disabled and the Promotion Governor has not approved `LIVE_ELIGIBLE`.

The `Completion Acceptance` workflow produces the canonical exact-head acceptance artifact for every relevant branch change. The checked-in `docs/ACCEPTANCE_REPORT.md` is a provenance snapshot of the last fully verified implementation baseline; it does not replace the exact-head workflow artifact.

## Strategy Universe V1

Strategy Universe V1 adds a versioned catalog of named strategy recipes and research targets without replacing MasterTrd's existing execution semantics. An `EXECUTABLE` recipe compiles deterministically into the shared `StrategyGenome` contract, carries its recipe identity as `style=recipe:<recipe_id>`, and then uses the same ResearchBrain, specialist evidence, Promotion Governor, and NautilusTrader execution boundaries as legacy generated candidates.

The scheduled public-data research job now iterates exact executable crypto BAR recipe IDs and records `recipe_id` in its public artifact. It does not silently substitute a cheaper strategy for unsupported ideas: options recipes remain blocked until qualifying option-chain/Greeks evidence exists; HFT, scalping, order-book and market-making recipes remain blocked until the required real tick/L2/queue/latency evidence exists; provider-specific recipes remain blocked until that provider is explicitly admitted. Multi-leg candidates cannot be validated through the single-instrument Nautilus wrapper.

Provider capability and MasterTrd admission are deliberately separate facts. `docs/MARKET_PROVIDER_MATRIX.md` records the researched market/provider surface and its blockers. Binance remains the only admitted execution provider in Strategy Universe V1; the presence of an Interactive Brokers, Polymarket, Betfair, OKX, Deribit, Hyperliquid, Databento, Tardis, or other Nautilus integration does **not** authorize MasterTrd to trade through it. Future admissions require provider-specific data, paper/test, reconciliation, risk, credential-isolation, and Governor evidence before execution can be enabled.

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
pytest -q
```

For the admitted full stack, use the locked environment:

```bash
python -m pip install uv
uv lock --check
uv sync --locked --all-extras
uv run pytest -q
```

## Runtime modes

`RESEARCH`, `BACKTEST`, `PAPER`, `DEMO`, `TESTNET`, `LIVE`.

LIVE mode requires both `MASTERTRD_MODE=LIVE` and `LIVE_TRADING_ENABLED=true`; otherwise configuration fails closed. Do not enable either merely because implementation acceptance is green.

The persistent execution node belongs on local/portable compute or the disabled-by-default Oracle adapter. Vercel is not used as the low-latency trading runtime; it can be added later for a read-only dashboard/API if desired.

Operational setup, TESTNET owner inputs, Oracle deployment, emergency kill, recovery, rollback, and secret rotation are documented in `docs/OPERATIONS.md`.
