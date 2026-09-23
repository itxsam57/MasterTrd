from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from .bar_completeness import timeframe_milliseconds
from .binance_stream import BinancePublicMarketSource
from .contracts import MarketBar, RuntimeMode
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
    fixture_binance_instrument,
    load_public_binance_instrument,
    open_persistent_paper_session,
)
from .paper_archive import JsonPaperReportArchive
from .paper_portfolio import (
    JsonPaperPortfolioStore,
    NautilusStreamingPaperPortfolioExecution,
    PaperPortfolioJournal,
    PersistentPaperPortfolio,
    open_paper_portfolio,
)
from .paper_hardening import (
    load_public_binance_bar_history,
    paper_bootstrap_bar_limit,
    required_bar_history,
)
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .reconciliation import Reconciler
from .risk import RiskLimits
from .risk_runtime import RiskRuntime
from .risk_state import RiskStateProvider
from .runtime import RuntimeConfig
from .streaming import MarketStream, RawMarketPayload
from .venue import BinanceProduct, infer_binance_product


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


def _load_portfolio_manifest(path: str | Path) -> tuple[str, str, str, tuple[StrategyGenome, ...]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("portfolio manifest could not be read") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("portfolio manifest must be a JSON object")
    portfolio_id = raw.get("portfolio_id")
    candidates_raw = raw.get("candidates")
    manifest_code_hash = raw.get("code_hash")
    manifest_lock_hash = raw.get("lock_hash")
    if not isinstance(portfolio_id, str) or not portfolio_id.strip():
        raise RuntimeError("portfolio manifest requires portfolio_id")
    if not isinstance(manifest_code_hash, str) or not manifest_code_hash:
        raise RuntimeError("portfolio manifest requires code_hash")
    if not isinstance(manifest_lock_hash, str) or not manifest_lock_hash:
        raise RuntimeError("portfolio manifest requires lock_hash")
    if not isinstance(candidates_raw, list) or len(candidates_raw) < 2:
        raise RuntimeError("portfolio manifest requires at least two candidates")
    candidates: list[StrategyGenome] = []
    for value in candidates_raw:
        if not isinstance(value, dict):
            raise RuntimeError("portfolio candidates must be JSON objects")
        try:
            candidates.append(StrategyGenome(**value))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("portfolio candidate manifest is invalid") from exc
    if len({candidate.strategy_id for candidate in candidates}) != len(candidates):
        raise RuntimeError("paper portfolio strategy identities must be unique")
    if any(len(candidate.instruments) != 1 for candidate in candidates):
        raise RuntimeError("shared PAPER portfolio currently admits single-leg strategies only")
    if any(tuple(candidate.data_requirements) != ("BAR",) for candidate in candidates):
        raise RuntimeError("shared PAPER portfolio currently admits BAR strategies only")
    return portfolio_id.strip(), manifest_code_hash, manifest_lock_hash, tuple(candidates)


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


def _paper_product(
    instrument_ids: Sequence[str],
    environ: Mapping[str, str],
) -> BinanceProduct:
    try:
        inferred = infer_binance_product(instrument_ids)
    except ValueError as exc:
        raise RuntimeError("PAPER instrument product identity is invalid") from exc
    if inferred not in {BinanceProduct.SPOT, BinanceProduct.USD_M}:
        raise RuntimeError("PAPER supports Binance SPOT and USD_M only")
    configured = environ.get("MASTERTRD_BINANCE_PRODUCT", "").strip().upper()
    if configured:
        try:
            configured_product = BinanceProduct(configured)
        except ValueError as exc:
            raise RuntimeError("MASTERTRD_BINANCE_PRODUCT is invalid") from exc
        if configured_product is not inferred:
            raise RuntimeError(
                "MASTERTRD_BINANCE_PRODUCT does not match PAPER candidate instruments"
            )
    return inferred


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


def _public_paper_first_expected_start_ms(
    initial_bars: Sequence[MarketBar],
    *,
    timeframe: str,
) -> int:
    """Return the first live candle start after authoritative bootstrap history."""

    if not initial_bars:
        raise RuntimeError("public PAPER bootstrap closed-bar identity is unavailable")
    latest = initial_bars[-1]
    raw_close_ms = latest.extras.get("source_kline_close_ms")
    if isinstance(raw_close_ms, bool):
        raise RuntimeError("public PAPER bootstrap closed-bar identity is invalid")
    try:
        close_ms = int(raw_close_ms)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("public PAPER bootstrap closed-bar identity is invalid") from exc
    if close_ms < 0:
        raise RuntimeError("public PAPER bootstrap closed-bar identity is invalid")

    timestamp_ms = int(round(latest.timestamp.timestamp() * 1_000.0))
    if timestamp_ms != close_ms:
        raise RuntimeError("public PAPER bootstrap closed-bar identity does not match history")

    try:
        width_ms = timeframe_milliseconds(timeframe)
    except ValueError as exc:
        raise RuntimeError("public PAPER completeness requires a fixed Binance timeframe") from exc
    first_expected_start_ms = close_ms + 1
    if first_expected_start_ms % width_ms != 0:
        raise RuntimeError("public PAPER bootstrap closed-bar identity is not timeframe-aligned")
    return first_expected_start_ms


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
    product = _paper_product(candidate.instruments, environ)

    fixture_path = environ.get("MASTERTRD_PUBLIC_FEED_FIXTURE", "").strip()
    initial_bars: Sequence[MarketBar] = ()
    first_expected_start_ms: int | None = None
    if fixture_path:
        instrument = fixture_binance_instrument(candidate.instruments[0])
    else:
        instrument = load_public_binance_instrument(
            candidate.instruments[0],
            product=product.value,
        )
        initial_bars = load_public_binance_bar_history(
            candidate.instruments[0],
            candidate.timeframe,
            limit=paper_bootstrap_bar_limit(candidate),
        )
        minimum_history = required_bar_history(candidate)
        if len(initial_bars) < minimum_history:
            raise RuntimeError(
                f"public PAPER history is insufficient for strategy warmup: "
                f"{len(initial_bars)}/{minimum_history} closed bars"
            )
        first_expected_start_ms = _public_paper_first_expected_start_ms(
            initial_bars,
            timeframe=candidate.timeframe,
        )

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
    public_source: BinancePublicMarketSource | None = None
    if fixture_path:
        stream = MarketStream(_fixture_source(fixture_path))
        state_provider = RiskStateProvider(
            clock=lambda: journal_ref["journal"].latest_timestamp_ns / 1_000_000_000.0,
        )
    else:
        if first_expected_start_ms is None:
            raise RuntimeError("public PAPER completeness anchor is unavailable")
        public_source = BinancePublicMarketSource(
            candidate.instruments,
            timeframe=candidate.timeframe,
            first_expected_start_ms=first_expected_start_ms,
            recovery_grace_ms=0,
            product=product,
        )
        stream = MarketStream(public_source)
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

    telemetry_provider = None
    if public_source is not None:
        def telemetry_provider() -> Mapping[str, object] | None:
            snapshot = public_source.completeness_snapshot
            return None if snapshot is None else asdict(snapshot)

    execution = NautilusStreamingPaperExecution(
        candidate=candidate,
        risk_runtime=risk_runtime,
        journal=session.journal,
        instrument=instrument,
        initial_bars=initial_bars,
        telemetry_provider=telemetry_provider,
        product=product,
    )
    account_id_ref = {"value": f"paper:{session.journal.session_id}"}

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



def _portfolio_strategy_token(strategy_id: str) -> str:
    return hashlib.sha256(strategy_id.encode()).hexdigest()[:12]


def _portfolio_archive_path(base: Path, strategy_id: str) -> Path:
    suffix = base.suffix or ".json"
    return base.with_name(f"{base.stem}-{_portfolio_strategy_token(strategy_id)}{suffix}")


def _archive_finalized_paper_portfolio(
    journal: PaperPortfolioJournal,
    *,
    archive_path: Path,
    history_dir: Path,
) -> None:
    for strategy_id in journal.strategy_ids:
        strategy_journal = journal.journal(strategy_id)
        report = strategy_journal.finalized_report
        if report is None:
            raise ValueError("paper portfolio must be finalized before archival")
        archive = JsonPaperReportArchive(_portfolio_archive_path(archive_path, strategy_id))
        strategy_history = history_dir / _portfolio_strategy_token(strategy_id)
        history_path = strategy_history / f"{strategy_journal.session_id}.json"
        history_store = JsonPaperSessionStore(history_path)
        if history_path.exists():
            existing = history_store.load()
            if existing.finalized_report != report:
                raise ValueError("conflicting finalized paper portfolio history already exists")
        else:
            history_store.save(strategy_journal)
        archive.append(report)


def _portfolio_finalized_end_ns(journal: PaperPortfolioJournal) -> int:
    reports = [journal.journal(strategy_id).finalized_report for strategy_id in journal.strategy_ids]
    if any(report is None for report in reports):
        raise ValueError("paper portfolio is not fully finalized")
    return max(
        _finalized_session_end_ns(journal.journal(strategy_id))
        for strategy_id in journal.strategy_ids
    )


def _next_portfolio_session_nonce(base_nonce: str, journal: PaperPortfolioJournal) -> str:
    material = "|".join(
        sorted(journal.journal(strategy_id).session_id for strategy_id in journal.strategy_ids)
    )
    return f"{base_nonce}:rotation:{hashlib.sha256(material.encode()).hexdigest()[:16]}"


def _open_replacement_paper_portfolio(
    candidates: Sequence[StrategyGenome],
    *,
    portfolio_id: str,
    state_path: Path,
    code_hash: str,
    started_ns: int,
    session_nonce: str,
) -> PersistentPaperPortfolio:
    next_path = state_path.with_name(f".{state_path.name}.next")
    next_path.unlink(missing_ok=True)
    replacement = open_paper_portfolio(
        candidates,
        portfolio_id=portfolio_id,
        state_path=next_path,
        code_hash=code_hash,
        started_ns=started_ns,
        session_nonce=session_nonce,
        resume=False,
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(next_path, state_path)
    return PersistentPaperPortfolio(
        journal=replacement.journal,
        store=JsonPaperPortfolioStore(state_path),
        resumed=False,
    )


def _paper_portfolio_runtime(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
) -> ExecutionRuntime:
    del runtime
    portfolio_id, manifest_code_hash, manifest_lock_hash, candidates = _load_portfolio_manifest(
        _required(environ, "MASTERTRD_PORTFOLIO_MANIFEST")
    )
    state_path = Path(_required(environ, "MASTERTRD_SESSION_STATE"))
    code_hash = _required(environ, "MASTERTRD_CODE_HASH")
    if manifest_code_hash != code_hash:
        raise RuntimeError("portfolio manifest code_hash does not match runtime code identity")
    lock_path = Path(__file__).resolve().parents[2] / "uv.lock"
    if not lock_path.is_file():
        raise RuntimeError("uv.lock is required for PAPER portfolio provenance")
    current_lock_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    if manifest_lock_hash != current_lock_hash:
        raise RuntimeError("portfolio manifest lock_hash does not match current uv.lock")
    instrument_ids = tuple(dict.fromkeys(
        candidate.instruments[0] for candidate in candidates
    ))
    product = _paper_product(instrument_ids, environ)
    timeframes = tuple(dict.fromkeys(candidate.timeframe for candidate in candidates))
    subscriptions = {
        timeframe: tuple(dict.fromkeys(
            candidate.instruments[0]
            for candidate in candidates
            if candidate.timeframe == timeframe
        ))
        for timeframe in timeframes
    }

    fixture_path = environ.get("MASTERTRD_PUBLIC_FEED_FIXTURE", "").strip()
    initial_bars: dict[str, Sequence[MarketBar]] = {}
    public_source: BinancePublicMarketSource | None = None

    if fixture_path:
        instruments = {
            instrument_id: fixture_binance_instrument(instrument_id)
            for instrument_id in instrument_ids
        }
        stream = MarketStream(_fixture_source(fixture_path))
    else:
        instruments = {
            instrument_id: load_public_binance_instrument(
                instrument_id,
                product=product.value,
            )
            for instrument_id in instrument_ids
        }
        anchors: dict[str, int] = {}
        for timeframe in timeframes:
            timeframe_anchors: set[int] = set()
            for instrument_id in subscriptions[timeframe]:
                matching = tuple(
                    candidate
                    for candidate in candidates
                    if candidate.instruments[0] == instrument_id
                    and candidate.timeframe == timeframe
                )
                required_limit = max(
                    paper_bootstrap_bar_limit(candidate) for candidate in matching
                )
                history = load_public_binance_bar_history(
                    instrument_id,
                    timeframe,
                    limit=required_limit,
                )
                minimum = max(required_bar_history(candidate) for candidate in matching)
                if len(history) < minimum:
                    raise RuntimeError(
                        "public PAPER history is insufficient for portfolio warmup: "
                        f"{instrument_id} {timeframe} {len(history)}/{minimum} closed bars"
                    )
                for candidate in matching:
                    initial_bars[candidate.strategy_id] = history
                timeframe_anchors.add(
                    _public_paper_first_expected_start_ms(
                        history,
                        timeframe=timeframe,
                    )
                )
            if len(timeframe_anchors) != 1:
                raise RuntimeError(
                    f"public PAPER portfolio bootstrap bars are not aligned for {timeframe}"
                )
            anchors[timeframe] = timeframe_anchors.pop()

        public_source = BinancePublicMarketSource(
            instrument_ids,
            timeframe=timeframes[0] if len(timeframes) == 1 else timeframes,
            subscriptions=subscriptions,
            first_expected_start_ms=(
                anchors[timeframes[0]] if len(timeframes) == 1 else anchors
            ),
            recovery_grace_ms=0,
            product=product,
        )
        stream = MarketStream(public_source)

    base_session_nonce = (
        environ.get("MASTERTRD_SESSION_NONCE", "portfolio-paper").strip()
        or "portfolio-paper"
    )
    evidence_paths = _paper_evidence_paths(environ)
    archive_path: Path | None = None
    history_dir: Path | None = None
    rotation_request_path: Path | None = None
    if evidence_paths is not None:
        archive_path, history_dir, rotation_request_path = evidence_paths

    resume = state_path.exists()
    if resume:
        session = open_paper_portfolio(
            candidates,
            portfolio_id=portfolio_id,
            state_path=state_path,
            code_hash=code_hash,
            started_ns=0,
            session_nonce=base_session_nonce,
            resume=True,
        )
        finalized = tuple(
            session.journal.journal(strategy_id).finalized_report is not None
            for strategy_id in session.journal.strategy_ids
        )
        if any(finalized) and not all(finalized):
            raise RuntimeError("persisted PAPER portfolio is only partially finalized")
        if all(finalized):
            if archive_path is None or history_dir is None:
                raise RuntimeError(
                    "finalized PAPER portfolio requires evidence archive configuration"
                )
            ended_ns = _portfolio_finalized_end_ns(session.journal)
            _archive_finalized_paper_portfolio(
                session.journal,
                archive_path=archive_path,
                history_dir=history_dir,
            )
            if rotation_request_path is not None:
                rotation_request_path.unlink(missing_ok=True)
            session = _open_replacement_paper_portfolio(
                candidates,
                portfolio_id=portfolio_id,
                state_path=state_path,
                code_hash=code_hash,
                started_ns=ended_ns,
                session_nonce=_next_portfolio_session_nonce(
                    base_session_nonce,
                    session.journal,
                ),
            )
            resume = False
    else:
        session = open_paper_portfolio(
            candidates,
            portfolio_id=portfolio_id,
            state_path=state_path,
            code_hash=code_hash,
            started_ns=_configured_new_paper_start_ns(environ),
            session_nonce=base_session_nonce,
            resume=False,
        )

    journal_ref = {"journal": session.journal}
    if fixture_path:
        state_provider = RiskStateProvider(
            clock=lambda: journal_ref["journal"].latest_timestamp_ns / 1_000_000_000.0,
        )
    else:
        state_provider = RiskStateProvider()
    for instrument_id in instrument_ids:
        state_provider.update_account_state(
            symbol=instrument_id,
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

    telemetry_provider = None
    if public_source is not None:
        def telemetry_provider(candidate: StrategyGenome) -> Mapping[str, object] | None:
            snapshot = public_source.completeness_snapshots.get(candidate.timeframe)
            return None if snapshot is None else asdict(snapshot)

    execution = NautilusStreamingPaperPortfolioExecution(
        candidates=candidates,
        risk_runtime=risk_runtime,
        journal=session.journal,
        instruments=instruments,
        initial_bars=initial_bars,
        telemetry_provider=telemetry_provider,
        product=product,
    )
    account_id = f"paper-portfolio:{portfolio_id}"
    state = lambda: execution.execution_state(account_id=account_id)
    recovery_state = session.journal.execution_state_checkpoint if resume else None
    startup_expected_state = None if recovery_state is None else lambda state=recovery_state: state

    rotation_requested = None
    rotate_session = None
    if archive_path is not None and history_dir is not None and rotation_request_path is not None:
        rotation_requested = rotation_request_path.exists

        def rotate_session(
            ended_ns: int,
        ) -> tuple[PaperPortfolioJournal, JsonPaperPortfolioStore]:
            current = journal_ref["journal"]
            if any(
                current.journal(strategy_id).finalized_report is not None
                for strategy_id in current.strategy_ids
            ):
                raise RuntimeError("active PAPER portfolio evidence is already finalized")
            for strategy_id in current.strategy_ids:
                current.journal(strategy_id).finalize(ended_ns=int(ended_ns))
            JsonPaperPortfolioStore(state_path).save(current)
            _archive_finalized_paper_portfolio(
                current,
                archive_path=archive_path,
                history_dir=history_dir,
            )
            rotation_request_path.unlink(missing_ok=True)
            replacement = _open_replacement_paper_portfolio(
                candidates,
                portfolio_id=portfolio_id,
                state_path=state_path,
                code_hash=code_hash,
                started_ns=int(ended_ns),
                session_nonce=_next_portfolio_session_nonce(base_session_nonce, current),
            )
            execution.bind_journal(replacement.journal)
            journal_ref["journal"] = replacement.journal
            return replacement.journal, replacement.store

    return ExecutionRuntime(
        journal=session.journal,
        session_store=session.store,
        risk_runtime=risk_runtime,
        reconciler=Reconciler(),
        engine_state=state,
        venue_state=state,
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
    if runtime.mode is RuntimeMode.PAPER:
        if environ.get("MASTERTRD_PORTFOLIO_MANIFEST", "").strip():
            return _paper_portfolio_runtime(runtime, environ)
        return _paper_runtime(runtime, environ)
    if runtime.mode in (RuntimeMode.DEMO, RuntimeMode.TESTNET, RuntimeMode.LIVE):
        return _exchange_runtime(runtime, environ)
    if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
        raise RuntimeError(f"{runtime.mode} is not a persistent execution mode")
    raise RuntimeError(f"unsupported persistent execution mode: {runtime.mode}")
