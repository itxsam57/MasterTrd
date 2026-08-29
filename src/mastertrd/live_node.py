from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
import os
import signal
import time
from threading import Event
from typing import Any, Protocol

from .contracts import RuntimeMode
from .credentials import load_binance_credentials
from .execution import build_binance_execution_profile
from .runtime import RuntimeConfig
from .venue import BinanceProduct


class NodeReadiness(StrEnum):
    PAPER_READY = "PAPER_READY"
    EXCHANGE_READY = "EXCHANGE_READY"
    LIVE_READY = "LIVE_READY"


class ExecutionNode(Protocol):
    def run(self) -> Any: ...

    def dispose(self) -> Any: ...


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


def _default_node_builder(*, profile, account_id: str) -> ExecutionNode:
    # Keep Nautilus optional for core/PAPER installs. Exchange modes import the
    # authoritative engine only after the runtime and credential gates pass.
    from .nautilus_live import build_nautilus_binance_trading_node

    return build_nautilus_binance_trading_node(profile=profile, account_id=account_id)


def build_exchange_node(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
    *,
    product: BinanceProduct,
    node_builder: Callable[..., ExecutionNode] = _default_node_builder,
) -> ExecutionNode:
    if runtime.mode is RuntimeMode.PAPER:
        raise RuntimeError("PAPER mode cannot construct an exchange execution node")
    if runtime.mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
        raise RuntimeError(f"{runtime.mode} mode cannot construct an exchange execution node")
    if runtime.mode is RuntimeMode.LIVE and not runtime.live_trading_enabled:
        raise RuntimeError("LIVE mode requires live_trading_enabled=true")

    credentials = load_binance_credentials(runtime.mode, environ)
    if credentials is None:
        raise RuntimeError(f"{runtime.mode} mode has no exchange credential namespace")

    profile = build_binance_execution_profile(
        runtime=runtime,
        product=product,
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
    )
    return node_builder(profile=profile, account_id=credentials.account_id)


def run_exchange_service(
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
    *,
    product: BinanceProduct,
    node_builder: Callable[..., ExecutionNode] = _default_node_builder,
) -> NodeReadiness:
    readiness = preflight_node(runtime, environ)
    if readiness is NodeReadiness.PAPER_READY:
        raise RuntimeError("PAPER mode must use the isolated paper runtime")

    node = build_exchange_node(
        runtime,
        environ,
        product=product,
        node_builder=node_builder,
    )
    try:
        node.run()
    finally:
        node.dispose()
    return readiness


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


def run_service(
    environ: Mapping[str, str],
    *,
    register_signal: Callable[[int, Any], Any],
    sleep: Callable[[float], None],
    heartbeat: Callable[[NodeReadiness], None],
    interval_seconds: float = 30.0,
    node_builder: Callable[..., ExecutionNode] = _default_node_builder,
) -> NodeReadiness:
    runtime = RuntimeConfig.from_env(dict(environ))

    if runtime.mode in (RuntimeMode.DEMO, RuntimeMode.TESTNET, RuntimeMode.LIVE):
        try:
            product = BinanceProduct(environ.get("BINANCE_PRODUCT", "SPOT").strip().upper())
        except ValueError as exc:
            raise ValueError("BINANCE_PRODUCT must be SPOT, USD_M, or COIN_M") from exc
        return run_exchange_service(
            runtime,
            environ,
            product=product,
            node_builder=node_builder,
        )

    stopped = Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stopped.set()

    register_signal(signal.SIGINT, request_stop)
    register_signal(signal.SIGTERM, request_stop)
    return run_node(
        runtime,
        environ,
        stop_requested=stopped.is_set,
        sleep=sleep,
        heartbeat=heartbeat,
        interval_seconds=interval_seconds,
    )


def main() -> None:
    run_service(
        os.environ,
        register_signal=signal.signal,
        sleep=time.sleep,
        heartbeat=lambda state: print(f"MasterTrd heartbeat: {state}", flush=True),
    )


if __name__ == "__main__":
    main()
