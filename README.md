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
