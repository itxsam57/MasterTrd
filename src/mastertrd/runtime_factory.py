from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import time

from .binance_stream import BinancePublicMarketSource
from .contracts import RuntimeMode
from .execution_runtime import ExecutionRuntime
from .genome import StrategyGenome
from .nautilus_paper import (
    NautilusStreamingPaperExecution,
    fixture_binance_spot_instrument,
    load_public_binance_spot_instrument,
    open_persistent_paper_session,
)
from .reconciliation import ExecutionState, Reconciler
from .risk import RiskLimits
from .risk_runtime import RiskRuntime
from .risk_state import RiskStateProvider
from .runtime import RuntimeConfig
from .streaming import MarketStream, RawMarketPayload


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for persistent execution")
    return value


def _load_candidate(path: str | Path) -> StrategyGenome:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("candidate manifest could not be read") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("candidate manifest must be a JSON object")
    try:
        return StrategyGenome(**raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("candidate manifest is invalid") from exc


def _fixture_source(path: str | Path) -> Iterable[RawMarketPayload]:
    fixture = Path(path)
    try:
        with fixture.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"public feed fixture contains invalid JSON on line {line_number}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise RuntimeError(
                        f"public feed fixture line {line_number} must be a JSON object"
                    )
                yield payload
    except OSError as exc:
        raise RuntimeError("public feed fixture could not be read") from exc


def _paper_risk_limits() -> RiskLimits:
    """Conservative process defaults for forward PAPER execution.

    These values are intentionally finite and restrictive. Candidate-specific
    risk budgets can tighten them in later orchestration, but PAPER must never
    inherit the permissive historical-simulation profile.
    """

    return RiskLimits(
        max_order_notional=1_000.0,
        max_symbol_exposure=5_000.0,
        max_portfolio_exposure=10_000.0,
        max_daily_loss=500.0,
        max_drawdown=0.10,
        max_orders_per_minute=30,
        max_leverage=2.0,
        max_correlated_exposure=7_500.0,
        max_spread_bps=100.0,
        max_realized_volatility=0.50,
        duplicate_order_window_seconds=2.0,
        max_api_error_rate=0.20,
        max_api_latency_ms=3_000.0,
        max_reconciliation_age_seconds=60.0,
    )


def _initial_paper_state(session_id: str) -> ExecutionState:
    return ExecutionState(
        account_id=f"paper:{session_id}",
        positions={},
        open_order_ids=frozenset(),
        balances={},
    )


def _paper_runtime(runtime: RuntimeConfig, environ: Mapping[str, str]) -> ExecutionRuntime:
    candidate = _load_candidate(_required(environ, "MASTERTRD_CANDIDATE_MANIFEST"))
    session_path = Path(_required(environ, "MASTERTRD_SESSION_STATE"))
    code_hash = _required(environ, "MASTERTRD_CODE_HASH")
    session_nonce = environ.get("MASTERTRD_SESSION_NONCE", "runtime-paper").strip() or "runtime-paper"

    if len(candidate.instruments) != 1:
        raise RuntimeError("PAPER runtime currently requires one instrument")

    fixture_path = environ.get("MASTERTRD_PUBLIC_FEED_FIXTURE", "").strip()
    if fixture_path:
        instrument = fixture_binance_spot_instrument(candidate.instruments[0])
    else:
        # Resolve exact current exchange precision and trading filters before a
        # persistent session is created. A metadata/network failure therefore
        # cannot leave behind a half-initialized PAPER session.
        instrument = load_public_binance_spot_instrument(candidate.instruments[0])

    resume = session_path.exists()
    if resume:
        started_ns = None
    else:
        started_raw = environ.get("MASTERTRD_PAPER_START_NS", "").strip()
        if started_raw:
            try:
                started_ns = int(started_raw)
            except ValueError as exc:
                raise RuntimeError("MASTERTRD_PAPER_START_NS must be an integer") from exc
            if started_ns < 0:
                raise RuntimeError("MASTERTRD_PAPER_START_NS cannot be negative")
        else:
            started_ns = time.time_ns()

    session = open_persistent_paper_session(
        candidate,
        state_path=session_path,
        code_hash=code_hash,
        started_ns=started_ns,
        session_nonce=session_nonce,
        resume=resume,
    )

    if fixture_path:
        stream = MarketStream(_fixture_source(fixture_path))
        # Recorded fixtures replay historical exchange timestamps. Tie freshness
        # to the append-only journal clock so valid replay batches are not judged
        # against wall-clock time.
        state_provider = RiskStateProvider(
            clock=lambda: session.journal.latest_timestamp_ns / 1_000_000_000.0,
        )
    else:
        stream = MarketStream(
            BinancePublicMarketSource(
                candidate.instruments,
                timeframe=candidate.timeframe,
            )
        )
        # Real public PAPER uses wall-clock freshness. Missing or stale market
        # observations therefore remain fail-closed in RiskStateProvider.
        state_provider = RiskStateProvider()

    for symbol in candidate.instruments:
        state_provider.update_account_state(
            symbol=symbol,
            portfolio_id="default",
            symbol_exposure=0.0,
            portfolio_exposure=0.0,
            daily_pnl=0.0,
            drawdown=0.0,
            leverage=0.0,
            correlated_exposure=0.0,
        )
    risk_runtime = RiskRuntime(_paper_risk_limits(), state_provider=state_provider)
    risk_runtime.update_api_health(
        venue="BINANCE",
        healthy=True,
        error_rate=0.0,
        latency_ms=0.0,
    )

    execution = NautilusStreamingPaperExecution(
        candidate=candidate,
        risk_runtime=risk_runtime,
        journal=session.journal,
        instrument=instrument,
    )

    # Task 5 recovery tests separately verify mismatch kill-before-dispatch. For
    # the single-process sandbox the Nautilus engine is the venue simulator, so
    # both reconciliation views share the same process snapshot until the
    # engine-backed reconciliation adapter is enabled in the next Task 5 slice.
    execution_state = _initial_paper_state(session.journal.session_id)
    return ExecutionRuntime(
        journal=session.journal,
        session_store=session.store,
        risk_runtime=risk_runtime,
        reconciler=Reconciler(),
        engine_state=lambda: execution_state,
        venue_state=lambda: execution_state,
        dispatch=execution.dispatch,
        stream=stream,
        finalizer=execution.close,
    )


def build_execution_runtime(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
) -> ExecutionRuntime:
    """Build the canonical repository-owned persistent execution runtime.

    PAPER is process-backed today and uses Binance public market data plus
    Nautilus sandbox execution, with an explicit recorded-feed override for
    deterministic verification. DEMO/TESTNET/LIVE remain fail-closed until
    their mode-specific Nautilus adapters are constructed; no mode can fall
    back to another execution mode.
    """

    if runtime.mode is RuntimeMode.PAPER:
        return _paper_runtime(runtime, environ)
    if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
        raise RuntimeError(f"{runtime.mode} is not a persistent execution mode")
    raise RuntimeError(f"canonical {runtime.mode} execution adapter is not configured")
