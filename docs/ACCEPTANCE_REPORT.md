# MasterTrd Acceptance Report

This is the **checked-in provenance snapshot** of the last fully verified implementation baseline. A file committed to git cannot truthfully contain the SHA of the commit that contains itself, so the **exact-head workflow artifact** produced by `Completion Acceptance` is canonical for the current branch head. This snapshot records the hardened implementation baseline from workflow run `33380146485`.

- Source commit SHA: `c66443df60eadb3ac2edb03f4d23c699c9d24600`
- Lock SHA-256: `ab8f78f5f42cec2fdd92fd0e0c94836ad37204f9e668bb47a7d718b7a4ecc9b7`
- Acceptance artifact digest: `sha256:ec1c20519dd9d0aa7678fe863fe116c4fae4850180170b5d13f367f5e2282019`
- Implementation status: `COMPLETE`
- LIVE eligible: `false`
- Promotion Governor approved: `false`
- Cumulative tests: `329 passed`
- Core coverage: `90%` with the required 90% threshold unchanged

## Mandatory suites

| Suite | Result | Detail |
| --- | --- | --- |
| `locked_install` | `PASS` | locked full stack installed from `uv.lock` and dependency compatibility checked |
| `cumulative_tests_and_coverage` | `PASS` | 329 cumulative tests passed and the independent core coverage gate reported 90% |
| `public_repo_safety` | `PASS` | committed-content secret scan, high-risk credential grep, and dependency audit passed |
| `clean_checkout` | `PASS` | working tree and index were clean and `git rev-parse HEAD` matched the workflow SHA |
| `integrated_research` | `PASS` | specialist/research integration workflow passed on the same source SHA |
| `full_stack` | `PASS` | all admitted external engines imported and the cumulative suite passed on the same source SHA |

## Execution-risk hardening included in this baseline

- `RiskRuntime` owns its rolling one-minute accepted-order rate instead of trusting strategy snapshots.
- Non-HFT Nautilus strategy compilation refuses a missing `risk_runtime` dependency.
- Direct risk-managed Nautilus strategy construction also refuses a missing runtime; there is no implicit permissive fallback.
- Historical evaluation uses the explicitly named `build_research_backtest_risk_runtime()` profile at the backtest boundary only.
- PAPER/DEMO/TESTNET/LIVE orchestration remains responsible for injecting its own runtime and limits.

## Live-eligibility evidence

| Probe | Status | Detail |
| --- | --- | --- |
| `risk_review` | `PASS` | focused live-evidence/risk runtime verification passed |
| `reconciliation_test` | `PASS` | reconciliation evidence verification passed |
| `kill_switch_test` | `PASS` | kill-switch evidence verification passed |
| `testnet_smoke` | `BLOCKED_OWNER_INPUT` | real TESTNET credentials and venue evidence must be supplied by the owner; no simulated result is accepted |

## Dataset fixtures

- `deterministic_bar_fixture`
- `real_l2_integrity_fixture`

## Engine versions

- `duckdb`: `1.5.5`
- `hftbacktest`: `2.4.4`
- `nautilus-trader`: `1.231.0`
- `optuna`: `4.9.0`
- `pyarrow`: `25.0.1`
- `pymoo`: `0.6.2`
- `python`: `3.13.15`
- `vectorbt`: `0.28.5`

## Owner input blockers

- `testnet_smoke`: supply the approved Binance TESTNET key/secret/account ID through the protected `testnet` GitHub Environment, with no withdrawal permission, then run the real TESTNET smoke workflow.
- Promotion Governor approval remains false until the coherent live-evidence bundle, including real TESTNET evidence, is complete.
- Oracle deployment requires the owner-controlled host/environment inputs documented in `docs/OPERATIONS.md` if that deployment target is chosen.
- Any later LIVE activation is a separate deliberate owner action after TESTNET evidence and Governor approval; implementation completion does not activate LIVE.

## Safety conclusion

LIVE remains disabled by default. Implementation completion does not activate LIVE trading. A real TESTNET smoke, coherent live-evidence bundle, Promotion Governor approval, and deliberate owner-controlled LIVE configuration are still required before any LIVE activation.

For the newest commit, use the `mastertrd-acceptance-<SHA>` artifact from the `Completion Acceptance` workflow. That generated artifact is the exact-head source of truth; this checked-in snapshot is provenance for the verified implementation baseline above.
