# MasterTrd

Autonomous quantitative research, validation, paper/demo/testnet, and controlled live-trading platform.

`MASTER_PLAN.md` is the canonical specification.

## Safety defaults

- `LIVE_TRADING_ENABLED=false`
- No exchange secrets belong in git.
- Trading keys must have **no withdrawal permission**.
- No strategy can become live-eligible without the Promotion Governor.

## Current implementation gate

Foundation: contracts, deterministic strategy genomes, promotion/risk governors, research memory, tests, and CI.

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
pytest -q
```

## Runtime modes

`RESEARCH`, `BACKTEST`, `PAPER`, `DEMO`, `TESTNET`, `LIVE`.

Live mode requires both `MASTERTRD_MODE=LIVE` and `LIVE_TRADING_ENABLED=true`; otherwise configuration fails closed.