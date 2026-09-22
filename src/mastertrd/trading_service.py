from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from enum import StrEnum
import os
import signal
import time
from pathlib import Path
from threading import Event
from typing import Any

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .runtime import RuntimeConfig
from .runtime_factory import build_execution_runtime
from .strategy_universe import STRATEGY_RECIPES


class TradingReadiness(StrEnum):
    PAPER_READY = "PAPER_READY"
    EXCHANGE_READY = "EXCHANGE_READY"
    LIVE_READY = "LIVE_READY"


RuntimeFactory = Callable[[RuntimeConfig, Mapping[str, str]], Any]


_STRATEGY_TELEMETRY_FIELDS = (
    "bars_seen",
    "bars_required",
    "warmup_remaining",
    "bootstrap_bars",
    "live_bars",
    "last_signal",
    "last_signal_reason",
    "last_exit_reason",
    "orders_attempted",
    "orders_allowed",
    "orders_rejected",
    "last_risk_rejection",
    "expected_closed_bars",
    "ws_closed_bars",
    "rest_recovered_bars",
    "missing_closed_bars",
    "recovery_failures",
    "last_closed_bar_ms",
    "last_expected_close_ms",
    "last_recovery_error",
    "data_healthy",
)


def paper_status_payload(
    journal: PaperSessionJournal,
    *,
    observed_ns: int,
) -> dict[str, object]:
    observed_ns = int(observed_ns)
    if observed_ns < journal.started_ns:
        raise ValueError("observed_ns cannot be before session start")
    if observed_ns < journal.latest_timestamp_ns:
        raise ValueError("observed_ns cannot be before the latest session event")

    trade_returns = [float(event.value) for event in journal._events if event.kind == "closed_trade"]
    reconciliation = [bool(event.value) for event in journal._events if event.kind == "reconciliation"]
    market_events = sum(1 for event in journal._events if event.kind == "market_event")

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in trade_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    execution_state = journal.execution_state_checkpoint
    payload: dict[str, object] = {
        "schema_version": 1,
        "strategy_id": journal.strategy_id,
        "genome_hash": journal.genome_hash,
        "code_hash": journal.code_hash,
        "session_id": journal.session_id,
        "duration_seconds": (observed_ns - journal.started_ns) // 1_000_000_000,
        "market_events": market_events,
        "closed_trades": len(trade_returns),
        "total_return": equity - 1.0,
        "max_drawdown": max_drawdown,
        "reconciliation_checks": len(reconciliation),
        "reconciliation_errors": sum(1 for ok in reconciliation if not ok),
        "position_count": 0 if execution_state is None else len(execution_state.positions),
        "open_order_count": 0 if execution_state is None else len(execution_state.open_order_ids),
        "latest_timestamp_ns": journal.latest_timestamp_ns,
        "finalized": journal.finalized_report is not None,
    }
    # PAPER Status can be newer than the currently deployed read-only journal
    # reader during a rolling upgrade. Pre-telemetry journals legitimately lack
    # this attribute; all canonical identity/evidence above must still be
    # reportable without weakening validation or fabricating telemetry.
    telemetry = getattr(journal, "strategy_telemetry", None)
    if telemetry is not None:
        for key in _STRATEGY_TELEMETRY_FIELDS:
            if key in telemetry:
                payload[key] = telemetry[key]
    return payload

class TradingService:
    paper_status_payload = staticmethod(paper_status_payload)
    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_factory: RuntimeFactory = build_execution_runtime,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._environ = environ
        self._runtime_factory = runtime_factory
        self._clock_ns = clock_ns

    def _environment(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def _runtime_config(self) -> RuntimeConfig:
        return RuntimeConfig.from_env(dict(self._environment()))

    def preflight(self) -> TradingReadiness:
        environ = dict(self._environment())
        runtime = RuntimeConfig.from_env(environ)
        if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
            raise RuntimeError(f"{runtime.mode} is not a persistent execution mode")
        if runtime.mode is RuntimeMode.PAPER:
            return TradingReadiness.PAPER_READY

        load_binance_credentials(runtime.mode, environ)
        if runtime.mode is RuntimeMode.LIVE:
            return TradingReadiness.LIVE_READY
        return TradingReadiness.EXCHANGE_READY

    def run(
        self,
        *,
        stop_requested: Callable[[], bool],
        heartbeat: Callable[[TradingReadiness], None] | None = None,
    ) -> TradingReadiness:
        readiness = self.preflight()
        if heartbeat is not None:
            heartbeat(readiness)
        runtime = self._runtime_factory(self._runtime_config(), dict(self._environment()))
        try:
            runtime.run(stop_requested=stop_requested)
        finally:
            close = getattr(runtime, "close", None)
            if callable(close):
                close()
        return readiness

    def run_forever(
        self,
        *,
        register_signal: Callable[[int, Any], Any] = signal.signal,
        heartbeat: Callable[[TradingReadiness], None] | None = None,
    ) -> TradingReadiness:
        stopped = Event()

        def request_stop(_signum: int, _frame: Any) -> None:
            stopped.set()

        register_signal(signal.SIGINT, request_stop)
        register_signal(signal.SIGTERM, request_stop)
        return self.run(stop_requested=stopped.is_set, heartbeat=heartbeat)

    def snapshot(self) -> dict[str, Any]:
        runtime = self._runtime_config()
        readiness = Counter(recipe.readiness.value for recipe in STRATEGY_RECIPES)
        payload: dict[str, Any] = {
            "mode": runtime.mode.value,
            "live_enabled": runtime.live_trading_enabled,
            "strategy_count": len(STRATEGY_RECIPES),
            "readiness": dict(sorted(readiness.items())),
        }
        session_path = self._environment().get("MASTERTRD_SESSION_STATE", "").strip()
        if runtime.mode is RuntimeMode.PAPER and session_path and Path(session_path).is_file():
            journal = JsonPaperSessionStore(session_path).load()
            payload["paper"] = self.paper_status_payload(
                journal,
                observed_ns=self._clock_ns(),
            )
        return payload

    def start_paper_cycle(self, *, candidate: Any, session_nonce: str) -> Any:
        from .paper_cycle import start_generated_paper_cycle
        return start_generated_paper_cycle(candidate=candidate, session_nonce=session_nonce)

    def finalize_paper_session(self, *, journal: PaperSessionJournal, session_store: JsonPaperSessionStore, archive: Any, ended_ns: int | None = None) -> Any:
        from .paper_cycle import finalize_forward_paper_session
        return finalize_forward_paper_session(journal=journal, session_store=session_store, archive=archive, ended_ns=self._clock_ns() if ended_ns is None else ended_ns)

    def strategy_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "recipe_id": recipe.recipe_id,
                "name": recipe.name,
                "family": recipe.family,
                "readiness": recipe.readiness.value,
                "assets": [asset.value for asset in recipe.asset_classes],
                "horizons": [horizon.value for horizon in recipe.horizons],
                "blocker": recipe.blocker,
            }
            for recipe in STRATEGY_RECIPES
        ]
