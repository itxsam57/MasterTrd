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


def test_live_node_is_only_a_compatibility_entrypoint():
    from pathlib import Path

    source = Path("src/mastertrd/live_node.py").read_text(encoding="utf-8")
    assert "TradingService" in source
    assert "def preflight_node" not in source
    assert "def run_node" not in source
    assert "def run_service" not in source


def test_paper_status_module_has_no_standalone_operator_cli():
    from pathlib import Path

    source = Path("src/mastertrd/paper_status.py").read_text(encoding="utf-8")
    assert "argparse" not in source
    assert 'if __name__ == "__main__"' not in source


def test_snapshot_includes_persisted_paper_session_status(tmp_path):
    from mastertrd.paper_evidence import PaperStartReceipt
    from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
    from mastertrd.trading_service import TradingService

    started = 1_000_000_000_000
    path = tmp_path / "paper-session.json"
    receipt = PaperStartReceipt(
        strategy_id="snapshot-paper",
        genome_hash="a" * 64,
        session_id="snapshot-session",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )
    journal = PaperSessionJournal(receipt, code_hash="snapshot-code", started_ns=started)
    journal.record_market_event("bar-1", timestamp_ns=started + 1_000_000_000)
    JsonPaperSessionStore(path).save(journal)

    snapshot = TradingService(
        {
            "MASTERTRD_MODE": "PAPER",
            "LIVE_TRADING_ENABLED": "false",
            "MASTERTRD_SESSION_STATE": str(path),
        },
        clock_ns=lambda: started + 2_000_000_000,
    ).snapshot()

    assert snapshot["paper"]["strategy_id"] == "snapshot-paper"
    assert snapshot["paper"]["session_id"] == "snapshot-session"
    assert snapshot["paper"]["market_events"] == 1
    assert snapshot["paper"]["duration_seconds"] == 2
