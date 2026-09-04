# Oracle Multi-Strategy Minute-Scale PAPER Design

## Purpose

Run multiple ResearchJob PAPER candidates concurrently on the Oracle execution host so MasterTrd can accumulate real forward PAPER evidence across strategies without waiting hours for a single 4h strategy.

## Safety invariants

- Every instance runs with `MASTERTRD_MODE=PAPER`.
- Every instance runs with `LIVE_TRADING_ENABLED=false`.
- Oracle deployment remains manual, protected by the `oracle` GitHub Environment, pinned SSH trust, exact-SHA checkout, and locked dependencies.
- Each candidate must be identity-bound to the deployed code hash and current `uv.lock` hash before any host mutation.
- Each strategy owns isolated candidate, session, archive, history, and rotation-request paths.
- No PAPER result may count as TESTNET or LIVE evidence, bypass the Promotion Governor, or enable LIVE.
- Existing risk, reconciliation, crash recovery, bar completeness, and kill-switch behavior remains authoritative.

## Architecture

Oracle Deploy accepts the complete public-safe `paper_candidates` set for one exact ResearchJob SHA instead of a single manifest. It validates every manifest first, rejects duplicate strategy/genome identities, and renders each canonical StrategyGenome to an isolated host directory.

The host uses a systemd template unit, `mastertrd-paper@.service`, so every PAPER candidate runs in a separate process with its own environment file and state directory while sharing only the exact locked source checkout and public Binance market-data access.

## PAPER windows and strategy cadence

Each strategy keeps its own native market timeframe and signal semantics; no strategy is rewritten merely to force trades. Evidence rotation is shortened from 86,400 seconds to 600 seconds so Oracle produces frequent independent PAPER reports and status snapshots. The fast execution-canary remains a separate infrastructure proof and never counts as alpha evidence.

Research candidates intended for this Oracle matrix should be minute-scale candidates emitted by the existing ResearchJob handoff. The deployment must not silently transform a 4h genome into a 1m genome; stale/slow candidates are visible in status rather than falsely accelerated.

## Deployment transaction

The workflow validates the full candidate list before SSH. On the host it refuses mutation if any existing configuration is LIVE-enabled, checks out the exact SHA, installs the locked environment, then materializes all candidate directories. A deployment generation is considered healthy only if every requested PAPER instance starts and passes its systemd health check.

Stale MasterTrd PAPER instances from a prior generation are stopped only after the new candidate set has been fully validated. The deployment never touches unrelated services or any owner-controlled LIVE configuration.

## Observability

A repository-owned Oracle PAPER status command aggregates every active strategy directory and reports strategy ID, genome hash, timeframe, current session, duration, closed trades, signal/risk telemetry, reconciliation state, and whether the service is active. Status output must contain no exchange credentials or private account payloads.

## Success criteria

- Multiple candidate manifests validate atomically against one exact SHA/lock.
- Two or more isolated PAPER instances can run concurrently without sharing mutable journals.
- PAPER evidence rotates on a 600-second schedule without restarting the strategy engine.
- Aggregate status distinguishes every strategy independently.
- Existing single-runtime PAPER tests, Oracle deployment safety tests, cumulative CI, security, and coverage gates remain green.
- Oracle host deployment keeps LIVE disabled for all PAPER instances.
