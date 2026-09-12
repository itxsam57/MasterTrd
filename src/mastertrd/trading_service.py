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
from .paper_session import JsonPaperSessionStore
from .paper_status import paper_status_payload as _paper_status_payload
from .runtime import RuntimeConfig
from .runtime_factory import build_execution_runtime
from .strategy_universe import STRATEGY_RECIPES


class TradingReadiness(StrEnum):
    PAPER_READY = "PAPER_READY"
    EXCHANGE_READY = "EXCHANGE_READY"
    LIVE_READY = "LIVE_READY"


RuntimeFactory = Callable[[RuntimeConfig, Mapping[str, str]], Any]


class TradingService:
    paper_status_payload = staticmethod(_paper_status_payload)
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
