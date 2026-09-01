from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import os
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
    PersistentPaperSession,
    fixture_binance_spot_instrument,
    load_public_binance_spot_instrument,
    open_persistent_paper_session,
)
from .paper_archive import JsonPaperReportArchive
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
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


def _paper_evidence_paths(
    environ: Mapping[str, str],
) -> tuple[Path, Path, Path] | None:
    names = (
        "MASTERTRD_PAPER_ARCHIVE",
        "MASTERTRD_PAPER_HISTORY_DIR",
        "MASTERTRD_PAPER_ROTATION_REQUEST",
    )
    values = tuple(environ.get(name, "").strip() for name in names)
    if not any(values):
        return None
    if not all(values):
        raise RuntimeError("PAPER evidence rotation paths must be configured together")
    return Path(values[0]), Path(values[1]), Path(values[2])


def _archive_finalized_paper_session(
    journal: PaperSessionJournal,
    *,
    archive: JsonPaperReportArchive,
    history_dir: Path,
) -> None:
    report = journal.finalized_report
    if report is None:
        raise ValueError("paper session must be finalized before archival")

    history_path = history_dir / f"{journal.session_id}.json"
    history_store = JsonPaperSessionStore(history_path)
    if history_path.exists():
        existing = history_store.load()
        if existing.finalized_report != report:
            raise ValueError("conflicting finalized paper session history already exists")
    else:
        history_store.save(journal)
    archive.append(report)


def _next_paper_session_nonce(
    base_nonce: str,
    archive: JsonPaperReportArchive,
) -> str:
    reports = archive.load()
    if not reports:
        return base_nonce
    latest = reports[-1]
    return f"{base_nonce}:rotation:{len(reports)}:{latest.session_id}"


def _finalized_session_end_ns(
    journal: PaperSessionJournal,
) -> int:
    report = journal.finalized_report
    if report is None:
        raise ValueError("paper session is not finalized")
    duration_end = journal.started_ns + int(report.duration_seconds) * 1_000_000_000
    return max(journal.latest_timestamp_ns, duration_end)


def _open_replacement_paper_session(
    candidate: StrategyGenome,
    *,
    session_path: Path,
    code_hash: str,
    started_ns: int,
    session_nonce: str,
) -> PersistentPaperSession:
    """Atomically replace current evidence state with a fresh empty session."""
    next_path = session_path.with_name(f".{session_path.name}.next")
    if next_path.exists():
        next_path.unlink()
    next_session = open_persistent_paper_session(
        candidate,
        state_path=next_path,
        code_hash=code_hash,
        started_ns=started_ns,
        session_nonce=session_nonce,
        resume=False,
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(next_path, session_path)
    return PersistentPaperSession(
        journal=next_session.journal,
        store=JsonPaperSessionStore(session_path),
        resumed=False,
    )


def _configured_new_paper_start_ns(environ: Mapping[str, str]) -> int:
    started_raw = environ.get("MASTERTRD_PAPER_START_NS", "").strip()
    if not started_raw:
        return time.time_ns()
    try:
        started_ns = int(started_raw)
    except ValueError as exc:
        raise RuntimeError("MASTERTRD_PAPER_START_NS must be an integer") from exc
    if started_ns < 0:
        raise RuntimeError("MASTERTRD_PAPER_START_NS cannot be negative")
    return started_ns


def _paper_runtime(runtime: RuntimeConfig, environ: Mapping[str, str]) -> ExecutionRuntime:
    candidate = _load_candidate(_required(environ, "MASTERTRD_CANDIDATE_MANIFEST"))
    session_path = Path(_required(environ, "MASTERTRD_SESSION_STATE"))
    code_hash = _required(environ, "MASTERTRD_CODE_HASH")
    base_session_nonce = (
        environ.get("MASTERTRD_SESSION_NONCE", "runtime-paper").strip() or "runtime-paper"
    )
    evidence_paths = _paper_evidence_paths(environ)

    if len(candidate.instruments) != 1:
        raise RuntimeError("PAPER runtime currently requires one instrument")

    # Resolve authoritative instrument metadata before touching durable session
    # state. A public-network metadata failure must not leave behind a session
    # file that falsely looks like a successfully initialized PAPER process.
    fixture_path = environ.get("MASTERTRD_PUBLIC_FEED_FIXTURE", "").strip()
    if fixture_path:
        instrument = fixture_binance_spot_instrument(candidate.instruments[0])
    else:
        instrument = load_public_binance_spot_instrument(candidate.instruments[0])

    archive: JsonPaperReportArchive | None = None
    history_dir: Path | None = None
    rotation_request_path: Path | None = None
    if evidence_paths is not None:
        archive_path, history_dir, rotation_request_path = evidence_paths
        archive = JsonPaperReportArchive(archive_path)

    resume = session_path.exists()
    session: PersistentPaperSession
    if resume:
        session = open_persistent_paper_session(
            candidate,
            state_path=session_path,
            code_hash=code_hash,
            session_nonce=base_session_nonce,
            resume=True,
        )
        if session.journal.finalized_report is not None and archive is not None and history_dir is not None:
            ended_ns = _finalized_session_end_ns(session.journal)
            _archive_finalized_paper_session(
                session.journal,
                archive=archive,
                history_dir=history_dir,
            )
            # Consume the request before replacing the official current state.
            # If the process dies after this point, restart recovery still sees
            # the finalized current session and advances it automatically. This
            # prevents a stale request from immediately rotating the fresh window.
            if rotation_request_path is not None:
                rotation_request_path.unlink(missing_ok=True)
            session = _open_replacement_paper_session(
                candidate,
                session_path=session_path,
                code_hash=code_hash,
                started_ns=ended_ns,
                session_nonce=_next_paper_session_nonce(base_session_nonce, archive),
            )
            resume = False
    else:
        started_ns = _configured_new_paper_start_ns(environ)
        session_nonce = base_session_nonce
        if archive is not None and archive.load():
            session_nonce = _next_paper_session_nonce(base_session_nonce, archive)
            latest = archive.load()[-1]
            if history_dir is not None:
                latest_history = history_dir / f"{latest.session_id}.json"
                if latest_history.exists():
                    started_ns = _finalized_session_end_ns(
                        JsonPaperSessionStore(latest_history).load()
                    )
        session = open_persistent_paper_session(
            candidate,
            state_path=session_path,
            code_hash=code_hash,
            started_ns=started_ns,
            session_nonce=session_nonce,
            resume=False,
        )

    journal_ref = {"journal": session.journal}
    if fixture_path:
        stream = MarketStream(_fixture_source(fixture_path))
        # Recorded fixtures replay historical exchange timestamps. Tie freshness
        # to the active append-only journal clock so rotated evidence windows do
        # not accidentally fall back to the original session's timestamp.
        state_provider = RiskStateProvider(
            clock=lambda: journal_ref["journal"].latest_timestamp_ns / 1_000_000_000.0,
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
    account_id_ref = {"value": f"paper:{session.journal.session_id}"}

    # During an active PAPER process Nautilus is both the authoritative engine
    # and simulated venue. A resumed session additionally carries the last
    # integrity-covered engine checkpoint from the prior process; that snapshot
    # is used only for startup recovery reconciliation before any new dispatch.
    engine_state = lambda: execution.execution_state(account_id=account_id_ref["value"])
    venue_state = lambda: execution.execution_state(account_id=account_id_ref["value"])
    recovery_state = session.journal.execution_state_checkpoint if resume else None
    startup_expected_state = (
        None if recovery_state is None else lambda state=recovery_state: state
    )

    rotation_requested = None
    rotate_session = None
    if archive is not None and history_dir is not None and rotation_request_path is not None:
        rotation_requested = rotation_request_path.exists

        def rotate_session(ended_ns: int) -> tuple[PaperSessionJournal, JsonPaperSessionStore]:
            current = journal_ref["journal"]
            if current.finalized_report is not None:
                raise RuntimeError("active PAPER evidence session is already finalized")
            current.finalize(ended_ns=int(ended_ns))
            JsonPaperSessionStore(session_path).save(current)
            _archive_finalized_paper_session(
                current,
                archive=archive,
                history_dir=history_dir,
            )
            # Once finalization and archival are durable, the request has been
            # fulfilled. Remove it before state replacement so a crash cannot
            # carry the old request into the next evidence window.
            rotation_request_path.unlink(missing_ok=True)
            replacement = _open_replacement_paper_session(
                candidate,
                session_path=session_path,
                code_hash=code_hash,
                started_ns=int(ended_ns),
                session_nonce=_next_paper_session_nonce(base_session_nonce, archive),
            )
            if replacement.journal.finalized_report is not None:
                raise RuntimeError("replacement PAPER evidence session must be open")
            execution.bind_journal(replacement.journal)
            journal_ref["journal"] = replacement.journal
            account_id_ref["value"] = f"paper:{replacement.journal.session_id}"
            return replacement.journal, replacement.store

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
        startup_expected_state=startup_expected_state,
        rotation_requested=rotation_requested,
        rotate_session=rotate_session,
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