from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from importlib import import_module
import os
import signal
import time
from threading import Event
from typing import Any

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .runtime import RuntimeConfig
from .runtime_factory import build_execution_runtime


class NodeReadiness(StrEnum):
    PAPER_READY = "PAPER_READY"
    EXCHANGE_READY = "EXCHANGE_READY"
    LIVE_READY = "LIVE_READY"


def preflight_node(runtime: RuntimeConfig, environ: Mapping[str, str]) -> NodeReadiness:
    if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
        raise RuntimeError(f"{runtime.mode} is not a persistent execution mode")

    if runtime.mode is RuntimeMode.PAPER:
        return NodeReadiness.PAPER_READY

    if runtime.mode is RuntimeMode.LIVE and not runtime.live_trading_enabled:
        raise RuntimeError("LIVE mode requires live_trading_enabled=true")

    load_binance_credentials(runtime.mode, environ)
    if runtime.mode is RuntimeMode.LIVE:
        return NodeReadiness.LIVE_READY
    return NodeReadiness.EXCHANGE_READY


def load_execution_runtime_factory(
    environ: Mapping[str, str],
) -> Callable[[RuntimeConfig, Mapping[str, str]], Any]:
    target = environ.get("MASTERTRD_EXECUTION_FACTORY", "").strip()
    if not target:
        raise RuntimeError(
            "MASTERTRD_EXECUTION_FACTORY must be configured for production execution"
        )

    module_name, separator, function_name = target.partition(":")
    if (
        separator != ":"
        or not module_name.strip()
        or not function_name.strip()
        or ":" in function_name
    ):
        raise ValueError("MASTERTRD_EXECUTION_FACTORY must use module:function format")

    module = import_module(module_name.strip())
    factory = getattr(module, function_name.strip(), None)
    if not callable(factory):
        raise TypeError("MASTERTRD_EXECUTION_FACTORY must reference a callable factory")
    return factory


def run_node(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
    *,
    stop_requested: Callable[[], bool],
    sleep: Callable[[float], None],
    heartbeat: Callable[[NodeReadiness], None],
    interval_seconds: float,
    execution_runtime: Any | None = None,
) -> NodeReadiness:
    readiness = preflight_node(runtime, environ)
    if execution_runtime is not None:
        heartbeat(readiness)
        try:
            execution_runtime.run(stop_requested=stop_requested)
        finally:
            execution_runtime.close()
        return readiness

    # Backward-compatible observability-only loop for injected/test callers.
    # Production main() uses the repository-owned runtime factory.
    while not stop_requested():
        heartbeat(readiness)
        sleep(interval_seconds)
    return readiness


def run_service(
    environ: Mapping[str, str],
    *,
    register_signal: Callable[[int, Any], Any],
    sleep: Callable[[float], None],
    heartbeat: Callable[[NodeReadiness], None],
    interval_seconds: float = 30.0,
    execution_runtime: Any | None = None,
    execution_runtime_factory: Callable[[RuntimeConfig, Mapping[str, str]], Any] | None = None,
) -> NodeReadiness:
    runtime = RuntimeConfig.from_env(dict(environ))
    stopped = Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stopped.set()

    register_signal(signal.SIGINT, request_stop)
    register_signal(signal.SIGTERM, request_stop)

    if execution_runtime is None and execution_runtime_factory is not None:
        execution_runtime = execution_runtime_factory(runtime, dict(environ))

    return run_node(
        runtime,
        environ,
        stop_requested=stopped.is_set,
        sleep=sleep,
        heartbeat=heartbeat,
        interval_seconds=interval_seconds,
        execution_runtime=execution_runtime,
    )


def main() -> None:
    run_service(
        os.environ,
        register_signal=signal.signal,
        sleep=time.sleep,
        heartbeat=lambda state: print(f"MasterTrd heartbeat: {state}", flush=True),
        execution_runtime_factory=build_execution_runtime,
    )


if __name__ == "__main__":
    main()
