import signal

import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.live_node import NodeReadiness, preflight_node, run_node, run_service
from mastertrd.runtime import RuntimeConfig


def runtime(mode: RuntimeMode, *, live: bool = False, oracle: bool = False) -> RuntimeConfig:
    return RuntimeConfig(mode=mode, live_trading_enabled=live, oracle_enabled=oracle)


def test_paper_node_is_ready_without_exchange_credentials():
    readiness = preflight_node(runtime(RuntimeMode.PAPER), {})
    assert readiness is NodeReadiness.PAPER_READY


def test_demo_and_testnet_require_their_own_credentials():
    with pytest.raises(ValueError, match="Missing Binance DEMO credentials"):
        preflight_node(runtime(RuntimeMode.DEMO), {})

    ready = preflight_node(
        runtime(RuntimeMode.TESTNET),
        {
            "BINANCE_TESTNET_API_KEY": "key",
            "BINANCE_TESTNET_API_SECRET": "secret",
            "BINANCE_TESTNET_ACCOUNT_ID": "acct",
        },
    )
    assert ready is NodeReadiness.EXCHANGE_READY


def test_live_requires_runtime_live_enable_and_live_credentials():
    with pytest.raises(RuntimeError, match="LIVE mode requires live_trading_enabled"):
        preflight_node(runtime(RuntimeMode.LIVE, live=False), {})

    with pytest.raises(ValueError, match="Missing Binance LIVE credentials"):
        preflight_node(runtime(RuntimeMode.LIVE, live=True), {})

    ready = preflight_node(
        runtime(RuntimeMode.LIVE, live=True),
        {
            "BINANCE_LIVE_API_KEY": "key",
            "BINANCE_LIVE_API_SECRET": "secret",
            "BINANCE_LIVE_ACCOUNT_ID": "acct",
        },
    )
    assert ready is NodeReadiness.LIVE_READY


def test_research_and_backtest_do_not_run_as_persistent_execution_nodes():
    for mode in (RuntimeMode.RESEARCH, RuntimeMode.BACKTEST):
        with pytest.raises(RuntimeError, match="not a persistent execution mode"):
            preflight_node(runtime(mode), {})


def test_run_node_stays_alive_until_stop_requested_after_preflight():
    stop_states = iter((False, False, True))
    sleeps: list[float] = []
    heartbeats: list[NodeReadiness] = []

    readiness = run_node(
        runtime(RuntimeMode.PAPER),
        {},
        stop_requested=lambda: next(stop_states),
        sleep=lambda seconds: sleeps.append(seconds),
        heartbeat=lambda state: heartbeats.append(state),
        interval_seconds=5.0,
    )

    assert readiness is NodeReadiness.PAPER_READY
    assert sleeps == [5.0, 5.0]
    assert heartbeats == [NodeReadiness.PAPER_READY, NodeReadiness.PAPER_READY]


def test_run_service_builds_runtime_and_stops_cleanly_on_sigterm():
    handlers: dict[int, object] = {}
    heartbeats: list[NodeReadiness] = []
    sleeps: list[float] = []

    def register(sig: int, handler: object) -> None:
        handlers[sig] = handler

    def heartbeat(state: NodeReadiness) -> None:
        heartbeats.append(state)
        handler = handlers[signal.SIGTERM]
        handler(signal.SIGTERM, None)  # type: ignore[operator]

    readiness = run_service(
        {
            "MASTERTRD_MODE": "PAPER",
            "LIVE_TRADING_ENABLED": "false",
            "ORACLE_ENABLED": "false",
        },
        register_signal=register,
        sleep=lambda seconds: sleeps.append(seconds),
        heartbeat=heartbeat,
        interval_seconds=3.0,
    )

    assert signal.SIGINT in handlers
    assert signal.SIGTERM in handlers
    assert readiness is NodeReadiness.PAPER_READY
    assert heartbeats == [NodeReadiness.PAPER_READY]
    assert sleeps == [3.0]
