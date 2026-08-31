# MasterTrd Acceptance Report

This is the **checked-in provenance snapshot** of the latest fully verified implementation baseline. A file committed to git cannot truthfully contain the SHA of the commit that contains itself, so the **exact-head workflow artifact** produced by `Completion Acceptance` remains canonical for the current branch head. This snapshot records the hardened implementation baseline from source commit `a76cdf85b4c1fadfd97d4ddec2267b4775f6bf1e` and acceptance run `33387500743`.

- Source commit SHA: `a76cdf85b4c1fadfd97d4ddec2267b4775f6bf1e`
- Lock SHA-256: `ab8f78f5f42cec2fdd92fd0e0c94836ad37204f9e668bb47a7d718b7a4ecc9b7`
- Acceptance artifact digest: `sha256:00d3d6e033002dfca4974952a66db7a5217cb78233077e111f68f11a57406298`
- Implementation status: `COMPLETE`
- LIVE eligible: `false`
- Promotion Governor approved: `false`
- Cumulative tests: `332 passed`
- Core coverage: `90%` with the required 90% threshold unchanged
- Exact-source CI run: `33387500715`
- Exact-source Full Stack run: `33387500750`
- Exact-source Execution Stack run: `33387500637`
- Exact-source Public Repo Security run: `33387500652`

## Mandatory suites

| Suite | Result | Detail |
| --- | --- | --- |
| `locked_install` | `PASS` | locked full stack installed from `uv.lock` and dependency compatibility checked |
| `cumulative_tests_and_coverage` | `PASS` | 332 cumulative tests passed and the independent core coverage gate reported 90% |
| `public_repo_safety` | `PASS` | committed-content secret scan, high-risk credential grep, and dependency audit passed |
| `clean_checkout` | `PASS` | working tree and index were clean and `git rev-parse HEAD` matched the workflow SHA |
| `execution_stack` | `PASS` | exact-source Nautilus Binance execution bridge gate passed in run `33387500637` |
| `full_stack` | `PASS` | all admitted external engines imported and the cumulative suite passed on exact source SHA `a76cdf85...` in run `33387500750` |
| `integrated_research` | `PASS` | last research-owned baseline passed in run `33380146504` on `c66443df...`; no research-owned source, dependency, or research workflow changed in the TESTNET hardening commits, and exact-source Full Stack remained green |

## TESTNET execution root-cause hardening included in this baseline

- Added a production `mastertrd.testnet_smoke` runner instead of treating credential/runtime preflight as venue evidence.
- TESTNET execution remains inside the authoritative NautilusTrader engine; no parallel direct-REST execution path was introduced.
- Binance instrument loading is now targeted through Nautilus `InstrumentProviderConfig(load_ids=...)`, avoiding an empty instrument cache while keeping `load_all=false`.
- The smoke probe creates one bounded Binance Spot TESTNET post-only BUY resting away from the top of book, sizes it against the venue minimum-notional/step/minimum-quantity rules, requires venue acceptance, and cancels outstanding orders during shutdown.
- The manual `Testnet Smoke` workflow now invokes the real production runner and uploads `artifacts/testnet_smoke.json` as exact-SHA evidence.
- The workflow continues to refuse non-TESTNET runtime, missing credentials, and any credential marked withdrawal-capable.
- Regression coverage now prevents the workflow from silently reverting to credential-only preflight.

## Existing execution-risk hardening retained

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
| `testnet_smoke` | `BLOCKED_OWNER_INPUT` | the real smoke path is implemented and verified structurally, but a venue receipt requires the owner-provided protected Binance TESTNET credentials and a manual workflow dispatch; no simulated result is accepted |

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

- `testnet_smoke`: supply the approved Binance TESTNET key/secret/account ID through the protected `testnet` GitHub Environment, with no withdrawal permission, then manually run the `Testnet Smoke` workflow. The workflow now performs the real bounded Nautilus venue probe and emits the exact-SHA JSON receipt.
- Promotion Governor approval remains false until the coherent live-evidence bundle, including real TESTNET venue evidence, is complete.
- Oracle deployment requires the owner-controlled host/environment inputs documented in `docs/OPERATIONS.md` if that deployment target is chosen.
- Any later LIVE activation is a separate deliberate owner action after TESTNET evidence and Governor approval; implementation completion does not activate LIVE.

## Safety conclusion

LIVE remains disabled by default. Implementation completion does not activate LIVE trading. The code-side TESTNET execution gap is closed; a real TESTNET venue receipt, coherent live-evidence bundle, Promotion Governor approval, and deliberate owner-controlled LIVE configuration are still required before any LIVE activation.

For the newest commit, use the `mastertrd-acceptance-<SHA>` artifact from the `Completion Acceptance` workflow. That generated artifact is the exact-head source of truth; this checked-in snapshot is provenance for the verified implementation baseline above.
