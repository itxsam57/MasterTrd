from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
import time

from .binance_stream import BinancePublicMarketSource
from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .execution import build_binance_execution_profile
from .execution_runtime import ExecutionRuntime
from .genome import StrategyGenome
from .nautilus_binance import (
    NautilusLiveExecutionRuntime,
    build_nautilus_binance_configs,
    build_nautilus_binance_node_config,
    build_nautilus_binance_trading_node,
)
from .nautilus_paper import (
    NautilusStreamingPaperExecution,
    fixture_binance_spot_instrument,
    load_public_binance_spot_instrument,
    open_persistent_paper_session,
)
from .reconciliation import Reconciler
from .risk import RiskLimits
from .risk_runtime import RiskRuntime
from .risk_state import RiskStateProvider
from .runtime import RuntimeConfig
from .streaming import MarketStream, RawMarketPayload
from .venue import BinanceProduct


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
    account_id = f"paper:{session.journal.session_id}"

    # PAPER has one authoritative Nautilus simulated venue/account. Both views
    # intentionally snapshot that live engine state rather than a fabricated
    # static seed; a later reconciliation slice compares this engine state with
    # journal-derived expected state for independent recovery verification.
    engine_state = lambda: execution.execution_state(account_id=account_id)
    venue_state = lambda: execution.execution_state(account_id=account_id)
    return ExecutionRuntime(
        journal=session.journal,
        session_store=session.store,
        risk_runtime=risk_runtime,
        reconciler=Reconciler(),
        engine_state=engine_state,
        venue_state=venue_state,
        dispatch=execution.dispatch,
        stream=stream,
        finalizer=execution.close,
    )


def _exchange_runtime(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
) -> NautilusLiveExecutionRuntime:
    """Build the real Nautilus Binance transport/reconciliation boundary.

    Exchange modes own their market-data and execution clients inside one
    ``TradingNode``. Candidate strategy promotion/identity binding remains a
    separate gate; this factory never silently selects or invents a strategy,
    but it does constrain the live node to the candidate's exact instrument
    universe so startup reconciliation cannot drift onto unrelated products.
    """
    if runtime.mode not in (RuntimeMode.DEMO, RuntimeMode.TESTNET, RuntimeMode.LIVE):
        raise RuntimeError(f"{runtime.mode} mode is not an exchange execution mode")
    if runtime.mode is RuntimeMode.LIVE and not runtime.live_trading_enabled:
        raise RuntimeError("LIVE mode requires live_trading_enabled=true")

    candidate = _load_candidate(_required(environ, "MASTERTRD_CANDIDATE_MANIFEST"))
    product_raw = _required(environ, "MASTERTRD_BINANCE_PRODUCT").upper()
    try:
        product = BinanceProduct(product_raw)
    except ValueError as exc:
        raise RuntimeError(
            "MASTERTRD_BINANCE_PRODUCT must be SPOT, USD_M, or COIN_M"
        ) from exc

    credentials = load_binance_credentials(runtime.mode, environ)
    if credentials is None:
        raise RuntimeError(f"{runtime.mode} credentials are unavailable")

    from nautilus_trader.model.identifiers import InstrumentId

    try:
        instrument_ids = tuple(InstrumentId.from_str(value) for value in candidate.instruments)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("candidate contains an invalid Nautilus instrument identity") from exc
    if len(set(instrument_ids)) != len(instrument_ids):
        raise RuntimeError("candidate instrument identities must be unique")
    if any(str(instrument_id.venue) != "BINANCE" for instrument_id in instrument_ids):
        raise RuntimeError("exchange runtime currently supports BINANCE candidate instruments only")

    profile = build_binance_execution_profile(
        runtime=runtime,
        product=product,
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
    )
    configs = build_nautilus_binance_configs(
        profile=profile,
        account_id=credentials.account_id,
        instrument_ids=frozenset(instrument_ids),
    )
    node_config = build_nautilus_binance_node_config(
        configs=configs,
        trader_id=f"MASTERTRD-{runtime.mode.value}-001",
        reconciliation_instrument_ids=instrument_ids,
        reconciliation_lookback_mins=1440,
    )
    node = build_nautilus_binance_trading_node(config=node_config)
    return NautilusLiveExecutionRuntime(node)


def build_execution_runtime(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
) -> ExecutionRuntime | NautilusLiveExecutionRuntime:
    """Build the canonical repository-owned persistent execution runtime.

    PAPER uses Binance public market data plus Nautilus sandbox execution.
    DEMO/TESTNET/LIVE use one repository-owned Nautilus ``TradingNode`` with
    mode-specific Binance credentials and mandatory startup reconciliation.
    No execution mode may silently fall back to another mode.
    """

    if runtime.mode is RuntimeMode.PAPER:
        return _paper_runtime(runtime, environ)
    if runtime.mode in (RuntimeMode.DEMO, RuntimeMode.TESTNET, RuntimeMode.LIVE):
        return _exchange_runtime(runtime, environ)
    if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
        raise RuntimeError(f"{runtime.mode} is not a persistent execution mode")
    raise RuntimeError(f"unsupported persistent execution mode: {runtime.mode}")
