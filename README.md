# MasterTrd

Autonomous quantitative research, validation, paper/demo/testnet, and controlled live-trading platform.

`MASTER_PLAN.md` is the canonical specification.

## Safety defaults

- `LIVE_TRADING_ENABLED=false`
- No exchange secrets belong in git.
- Trading keys must have **no withdrawal permission**.
- No strategy can become live-eligible without the Promotion Governor.

## Current implementation status

The original foundation is built, but **MasterTrd is not yet complete**. The foundation-only plan must not be used as the total project completion estimate.

The active end-to-end completion plan is:

`docs/superpowers/plans/2026-08-30-mastertrd-full-completion.md`

The completion track covers verified historical data ingestion, all strategy-family compiler paths, broad screening/optimization/evolution, the autonomous research brain, specialist validation, execution-risk wiring, persistent paper/demo/testnet runtime, reconciliation/recovery, real L2/HFT evidence, live-readiness evidence, deployment, and exact-SHA acceptance.

A dedicated `Completion Acceptance` workflow records cumulative verification artifacts. A green foundation/core test alone is not a claim that the complete product is done.

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

Live mode requires both `MASTERTRD_MODE=LIVE` and `LIVE_TRADING_ENABLED=true`; otherwise configuration fails closed.

The persistent execution node belongs on local/portable compute or the disabled-by-default Oracle adapter. Vercel is not used as the low-latency trading runtime; it can be added later for a read-only dashboard/API if desired.
