import signal

import pytest

import mastertrd.live_node as live_node
from mastertrd.contracts import RuntimeMode
from mastertrd.live_node import (
    NodeReadiness,
    load_execution_runtime_factory,
    preflight_node,
    run_node,
    run_service,
)
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


def test_run_node_delegates_to_execution_runtime_and_heartbeat_is_observability_only():
    class StubExecutionRuntime:
        def __init__(self) -> None:
            self.calls = 0
            self.stop_observed = True

        def run(self, *, stop_requested):
            self.calls += 1
            self.stop_observed = stop_requested()

    execution = StubExecutionRuntime()
    sleeps: list[float] = []
    heartbeats: list[NodeReadiness] = []

    readiness = run_node(
        runtime(RuntimeMode.PAPER),
        {},
        stop_requested=lambda: False,
        sleep=lambda seconds: sleeps.append(seconds),
        heartbeat=lambda state: heartbeats.append(state),
        interval_seconds=5.0,
        execution_runtime=execution,
    )

    assert readiness is NodeReadiness.PAPER_READY
    assert execution.calls == 1
    assert execution.stop_observed is False
    assert heartbeats == [NodeReadiness.PAPER_READY]
    assert sleeps == []


def test_run_service_can_build_concrete_execution_runtime_from_factory():
    handlers: dict[int, object] = {}
    heartbeats: list[NodeReadiness] = []
    built: list[tuple[RuntimeConfig, dict[str, str]]] = []

    class StubExecutionRuntime:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, *, stop_requested):
            self.calls += 1
            assert stop_requested() is False

    execution = StubExecutionRuntime()

    def factory(runtime_config: RuntimeConfig, environ: dict[str, str]):
        built.append((runtime_config, dict(environ)))
        return execution

    readiness = run_service(
        {
            "MASTERTRD_MODE": "PAPER",
            "LIVE_TRADING_ENABLED": "false",
            "ORACLE_ENABLED": "false",
        },
        register_signal=lambda sig, handler: handlers.__setitem__(sig, handler),
        sleep=lambda _seconds: pytest.fail("runtime-backed service must not heartbeat-sleep"),
        heartbeat=lambda state: heartbeats.append(state),
        execution_runtime_factory=factory,
    )

    assert readiness is NodeReadiness.PAPER_READY
    assert len(built) == 1
    assert built[0][0].mode is RuntimeMode.PAPER
    assert execution.calls == 1
    assert heartbeats == [NodeReadiness.PAPER_READY]
    assert signal.SIGINT in handlers and signal.SIGTERM in handlers


def test_production_factory_loader_fails_closed_when_unconfigured_or_invalid():
    with pytest.raises(RuntimeError, match="MASTERTRD_EXECUTION_FACTORY"):
        load_execution_runtime_factory({})
    for target in ("bad-format", ":factory", "module:", "module:function:extra"):
        with pytest.raises(ValueError, match="module:function"):
            load_execution_runtime_factory({"MASTERTRD_EXECUTION_FACTORY": target})


def test_production_factory_loader_resolves_callable_and_rejects_non_callable():
    factory = load_execution_runtime_factory(
        {"MASTERTRD_EXECUTION_FACTORY": "mastertrd.runtime:RuntimeConfig"}
    )
    assert factory is RuntimeConfig

    with pytest.raises(TypeError, match="callable factory"):
        load_execution_runtime_factory(
            {"MASTERTRD_EXECUTION_FACTORY": "mastertrd.live_node:signal"}
        )


def test_main_uses_repository_factory_without_external_factory_configuration(monkeypatch):
    sentinel_factory = object()
    calls: list[tuple[object, object]] = []

    monkeypatch.delenv("MASTERTRD_EXECUTION_FACTORY", raising=False)
    monkeypatch.setattr(live_node, "build_execution_runtime", sentinel_factory, raising=False)
    monkeypatch.setattr(
        live_node,
        "load_execution_runtime_factory",
        lambda _environ: pytest.fail("production main must not load arbitrary execution factory"),
    )

    def fake_run_service(environ, **kwargs):
        calls.append((environ, kwargs["execution_runtime_factory"]))
        return NodeReadiness.PAPER_READY

    monkeypatch.setattr(live_node, "run_service", fake_run_service)
    live_node.main()

    assert calls == [(live_node.os.environ, sentinel_factory)]


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
