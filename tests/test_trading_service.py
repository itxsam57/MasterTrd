from __future__ import annotations

import importlib
import importlib.util


def test_trading_service_module_is_the_local_runtime_boundary():
    assert importlib.util.find_spec("mastertrd.trading_service") is not None


def test_trading_service_exposes_one_consumer_runtime_service():
    module = importlib.import_module("mastertrd.trading_service")
    assert hasattr(module, "TradingService")
    assert hasattr(module, "TradingReadiness")


def test_snapshot_is_safe_by_default_and_exposes_full_strategy_catalog():
    from mastertrd.strategy_universe import STRATEGY_RECIPES
    from mastertrd.trading_service import TradingService

    service = TradingService({})
    snapshot = service.snapshot()
    rows = service.strategy_rows()

    assert snapshot["mode"] == "PAPER"
    assert snapshot["live_enabled"] is False
    assert snapshot["strategy_count"] == len(STRATEGY_RECIPES)
    assert len(rows) == len(STRATEGY_RECIPES)
    assert len(rows) >= 189
    assert {
        "recipe_id",
        "name",
        "family",
        "readiness",
        "assets",
        "horizons",
        "blocker",
    } <= rows[0].keys()


def test_preflight_preserves_paper_exchange_and_live_safety():
    import pytest

    from mastertrd.trading_service import TradingReadiness, TradingService

    assert TradingService({}).preflight() is TradingReadiness.PAPER_READY

    with pytest.raises(ValueError, match="Missing Binance TESTNET credentials"):
        TradingService({"MASTERTRD_MODE": "TESTNET"}).preflight()

    assert TradingService(
        {
            "MASTERTRD_MODE": "TESTNET",
            "BINANCE_TESTNET_API_KEY": "key",
            "BINANCE_TESTNET_API_SECRET": "secret",
            "BINANCE_TESTNET_ACCOUNT_ID": "acct",
        }
    ).preflight() is TradingReadiness.EXCHANGE_READY

    with pytest.raises(RuntimeError, match="LIVE mode requires LIVE_TRADING_ENABLED=true"):
        TradingService({"MASTERTRD_MODE": "LIVE"}).preflight()

    assert TradingService(
        {
            "MASTERTRD_MODE": "LIVE",
            "LIVE_TRADING_ENABLED": "true",
            "BINANCE_LIVE_API_KEY": "key",
            "BINANCE_LIVE_API_SECRET": "secret",
            "BINANCE_LIVE_ACCOUNT_ID": "acct",
        }
    ).preflight() is TradingReadiness.LIVE_READY



def test_preflight_rejects_research_and_backtest_persistent_modes():
    import pytest

    from mastertrd.trading_service import TradingService

    for mode in ("RESEARCH", "BACKTEST"):
        with pytest.raises(RuntimeError, match="not a persistent execution mode"):
            TradingService({"MASTERTRD_MODE": mode}).preflight()


def test_run_builds_one_runtime_heartbeats_and_closes_it():
    from mastertrd.contracts import RuntimeMode
    from mastertrd.trading_service import TradingReadiness, TradingService

    calls: list[object] = []

    class StubRuntime:
        def run(self, *, stop_requested):
            calls.append(("run", stop_requested()))

        def close(self):
            calls.append("close")

    runtime = StubRuntime()

    def factory(config, environ):
        calls.append(("factory", config.mode, dict(environ)))
        return runtime

    readiness = TradingService({}, runtime_factory=factory).run(
        stop_requested=lambda: False,
        heartbeat=lambda state: calls.append(("heartbeat", state)),
    )

    assert readiness is TradingReadiness.PAPER_READY
    assert calls == [
        ("heartbeat", TradingReadiness.PAPER_READY),
        ("factory", RuntimeMode.PAPER, {}),
        ("run", False),
        "close",
    ]


def test_run_closes_execution_runtime_when_run_raises():
    import pytest

    from mastertrd.trading_service import TradingService

    calls: list[str] = []

    class CrashingRuntime:
        def run(self, *, stop_requested):
            calls.append("run")
            assert stop_requested() is False
            raise RuntimeError("execution failed")

        def close(self):
            calls.append("close")

    with pytest.raises(RuntimeError, match="execution failed"):
        TradingService({}, runtime_factory=lambda _config, _environ: CrashingRuntime()).run(
            stop_requested=lambda: False,
        )

    assert calls == ["run", "close"]


def test_run_forever_registers_sigint_and_sigterm_before_runtime_start():
    import signal

    from mastertrd.trading_service import TradingReadiness, TradingService

    handlers: dict[int, object] = {}
    observed_stop: list[bool] = []

    class StubRuntime:
        def run(self, *, stop_requested):
            observed_stop.append(stop_requested())

        def close(self):
            return None

    readiness = TradingService(
        {},
        runtime_factory=lambda _config, _environ: StubRuntime(),
    ).run_forever(
        register_signal=lambda sig, handler: handlers.__setitem__(sig, handler),
        heartbeat=lambda _state: None,
    )

    assert readiness is TradingReadiness.PAPER_READY
    assert signal.SIGINT in handlers
    assert signal.SIGTERM in handlers
    assert observed_stop == [False]
