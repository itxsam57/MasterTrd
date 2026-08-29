from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .runtime import RuntimeConfig


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


def run_node(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
    *,
    stop_requested: Callable[[], bool],
    sleep: Callable[[float], None],
    heartbeat: Callable[[NodeReadiness], None],
    interval_seconds: float,
) -> NodeReadiness:
    readiness = preflight_node(runtime, environ)
    while not stop_requested():
        heartbeat(readiness)
        sleep(interval_seconds)
    return readiness
