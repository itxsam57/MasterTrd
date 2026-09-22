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


def test_paper_status_is_owned_by_trading_service_only():
    from pathlib import Path

    assert not Path("src/mastertrd/paper_status.py").exists()
    source = Path("src/mastertrd/trading_service.py").read_text(encoding="utf-8")
    assert "def paper_status_payload" in source


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


def test_portfolio_snapshot_exposes_strategy_and_account_state(tmp_path):
    import json

    from mastertrd.genome import StrategyGenome
    from mastertrd.paper_portfolio import open_paper_portfolio
    from mastertrd.reconciliation import ExecutionState
    from mastertrd.trading_service import TradingService

    def candidate(strategy_id, instrument):
        return StrategyGenome(
            strategy_id=strategy_id,
            family="trend",
            style="day",
            instruments=(instrument,),
            timeframe="1m",
            entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8},
            exit={"kind": "cross_reverse"},
        )

    candidates = (
        candidate("portfolio-a", "ETHUSDT.BINANCE"),
        candidate("portfolio-b", "BTCUSDT.BINANCE"),
    )
    manifest = tmp_path / "portfolio.json"
    manifest.write_text(
        json.dumps(
            {
                "portfolio_id": "local-paper",
                "candidates": [item.canonical_payload() for item in candidates],
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "portfolio-state.json"
    session = open_paper_portfolio(
        candidates,
        portfolio_id="local-paper",
        state_path=state,
        code_hash="code",
        started_ns=1_000_000_000,
    )
    session.journal.record_reconciliation(
        "reconcile:start",
        ok=True,
        timestamp_ns=2_000_000_000,
    )
    session.journal.record_execution_state(
        ExecutionState(
            account_id="paper-portfolio:local-paper",
            positions={"ETHUSDT.BINANCE": "0.1"},
            open_order_ids=frozenset(),
            balances={"USDT": "100000"},
        ),
        timestamp_ns=2_000_000_000,
    )
    session.store.save(session.journal)

    snapshot = TradingService(
        {
            "MASTERTRD_MODE": "PAPER",
            "MASTERTRD_PORTFOLIO_MANIFEST": str(manifest),
            "MASTERTRD_SESSION_STATE": str(state),
        },
        clock_ns=lambda: 3_000_000_000,
    ).snapshot()

    assert snapshot["portfolio"]["portfolio_id"] == "local-paper"
    assert {row["strategy_id"] for row in snapshot["portfolio"]["strategies"]} == {
        "portfolio-a",
        "portfolio-b",
    }
    assert snapshot["portfolio"]["positions"]["ETHUSDT.BINANCE"] == "0.1"
    assert snapshot["portfolio"]["reconciliation_errors"] == 0


def test_emergency_stop_is_persistent_visible_and_blocks_worker_start(tmp_path):
    import pytest

    from mastertrd.trading_service import TradingService

    stop_path = tmp_path / "EMERGENCY_STOP"
    service = TradingService(
        {
            "MASTERTRD_MODE": "PAPER",
            "MASTERTRD_EMERGENCY_STOP": str(stop_path),
        }
    )
    assert service.emergency_stop_active() is False
    service.activate_emergency_stop()
    assert stop_path.is_file()
    assert service.snapshot()["emergency_stop"] is True
    with pytest.raises(RuntimeError, match="emergency stop is active"):
        service.preflight()

    service.clear_emergency_stop()
    assert service.emergency_stop_active() is False


def test_live_emergency_stop_cannot_be_cleared_from_control_plane(tmp_path):
    import pytest

    from mastertrd.trading_service import TradingService

    stop_path = tmp_path / "EMERGENCY_STOP"
    stop_path.write_text("stop", encoding="utf-8")
    service = TradingService(
        {
            "MASTERTRD_MODE": "LIVE",
            "LIVE_TRADING_ENABLED": "true",
            "MASTERTRD_EMERGENCY_STOP": str(stop_path),
        }
    )
    with pytest.raises(RuntimeError, match="cannot clear emergency stop while LIVE"):
        service.clear_emergency_stop()


def test_local_settings_persist_only_safe_non_secret_runtime_fields(tmp_path, monkeypatch):
    import json

    from mastertrd.trading_service import TradingService

    config = tmp_path / "runtime.json"
    monkeypatch.setenv("MASTERTRD_LOCAL_CONFIG", str(config))
    for key in (
        "MASTERTRD_MODE",
        "LIVE_TRADING_ENABLED",
        "MASTERTRD_BINANCE_PRODUCT",
    ):
        monkeypatch.delenv(key, raising=False)

    service = TradingService()
    service.save_local_settings(mode="TESTNET", product="SPOT")
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload == {
        "MASTERTRD_MODE": "TESTNET",
        "LIVE_TRADING_ENABLED": "false",
        "MASTERTRD_BINANCE_PRODUCT": "SPOT",
    }
    assert service.snapshot()["mode"] == "TESTNET"
    assert service.provider_rows()[0]["credentials_configured"] is False


def test_local_settings_refuse_live_activation(tmp_path, monkeypatch):
    import pytest

    from mastertrd.trading_service import TradingService

    monkeypatch.setenv("MASTERTRD_LOCAL_CONFIG", str(tmp_path / "runtime.json"))
    with pytest.raises(RuntimeError, match="LIVE activation"):
        TradingService().save_local_settings(mode="LIVE", product="SPOT")


def test_configure_paper_portfolio_accepts_only_current_validated_finalists(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from mastertrd.genome import StrategyGenome
    from mastertrd.trading_service import TradingService

    config_path = tmp_path / "runtime.json"
    monkeypatch.setenv("MASTERTRD_LOCAL_CONFIG", str(config_path))
    service = TradingService()
    monkeypatch.setattr(service, "_current_code_hash", lambda: "code-current")
    monkeypatch.setattr(service, "_current_lock_hash", lambda: "lock-current")

    def manifest(strategy_id, instrument):
        candidate = StrategyGenome(
            strategy_id=strategy_id,
            family="trend",
            style="day",
            instruments=(instrument,),
            timeframe="1m",
            entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8},
            exit={"kind": "cross_reverse"},
        )
        return {
            "candidate": candidate.canonical_payload(),
            "strategy_id": candidate.strategy_id,
            "genome_hash": candidate.genome_hash,
            "state": "PAPER",
            "code_hash": "code-current",
            "dataset_hash": f"data-{strategy_id}",
            "lock_hash": "lock-current",
            "recipe_id": "ema-cross-fast",
        }

    configured = service.configure_paper_portfolio(
        [
            manifest("paper-a", "ETHUSDT.BINANCE"),
            manifest("paper-b", "BTCUSDT.BINANCE"),
        ],
        root=tmp_path / "trading",
    )
    payload = json.loads(Path(configured["manifest"]).read_text(encoding="utf-8"))
    assert payload["code_hash"] == "code-current"
    assert payload["lock_hash"] == "lock-current"
    assert len(payload["candidates"]) == 2
    settings = json.loads(config_path.read_text(encoding="utf-8"))
    assert settings["MASTERTRD_MODE"] == "PAPER"
    assert settings["LIVE_TRADING_ENABLED"] == "false"
    assert settings["MASTERTRD_PORTFOLIO_MANIFEST"] == configured["manifest"]
    assert settings["MASTERTRD_SESSION_STATE"] == configured["session_state"]
    assert settings["MASTERTRD_CODE_HASH"] == "code-current"
    assert settings["MASTERTRD_PAPER_ARCHIVE"].endswith("-reports.json")
    assert settings["MASTERTRD_PAPER_HISTORY_DIR"].endswith("-history")
    assert settings["MASTERTRD_PAPER_ROTATION_REQUEST"].endswith("-rotate.request")


def test_configure_paper_portfolio_rejects_unqualified_or_stale_finalists(tmp_path, monkeypatch):
    import pytest

    from mastertrd.genome import StrategyGenome
    from mastertrd.trading_service import TradingService

    monkeypatch.setenv("MASTERTRD_LOCAL_CONFIG", str(tmp_path / "runtime.json"))
    service = TradingService()
    monkeypatch.setattr(service, "_current_code_hash", lambda: "current-code")
    monkeypatch.setattr(service, "_current_lock_hash", lambda: "current-lock")
    candidate = StrategyGenome(
        strategy_id="paper-a",
        family="trend",
        style="day",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8},
        exit={"kind": "cross_reverse"},
    )
    base = {
        "candidate": candidate.canonical_payload(),
        "strategy_id": candidate.strategy_id,
        "genome_hash": candidate.genome_hash,
        "state": "PAPER",
        "code_hash": "current-code",
        "dataset_hash": "data",
        "lock_hash": "current-lock",
        "recipe_id": "ema-cross-fast",
    }
    with pytest.raises(ValueError, match="at least two"):
        service.configure_paper_portfolio([base], root=tmp_path / "trading")

    bad_state = dict(base, state="HIDDEN_PASS")
    with pytest.raises(ValueError, match="PAPER-qualified"):
        service.configure_paper_portfolio([base, bad_state], root=tmp_path / "trading")

    stale = dict(base, strategy_id="paper-b", code_hash="old-code")
    stale_candidate = StrategyGenome(
        strategy_id="paper-b",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 4, "slow_period": 9},
        exit={"kind": "cross_reverse"},
    )
    stale["candidate"] = stale_candidate.canonical_payload()
    stale["genome_hash"] = stale_candidate.genome_hash
    with pytest.raises(ValueError, match="code identity"):
        service.configure_paper_portfolio([base, stale], root=tmp_path / "trading")


def test_current_code_hash_requires_clean_exact_checkout(monkeypatch):
    import pytest

    from mastertrd.trading_service import TradingService

    monkeypatch.setattr("mastertrd.trading_service._source_git_head", lambda: "current-sha")
    assert TradingService({})._current_code_hash() == "current-sha"
    with pytest.raises(RuntimeError, match="does not match"):
        TradingService({"MASTERTRD_CODE_HASH": "stale-sha"})._current_code_hash()


def test_paper_evidence_rotation_request_is_persistent_and_requires_started_paper(tmp_path):
    import pytest

    from mastertrd.trading_service import TradingService

    state = tmp_path / "portfolio-state.json"
    request = tmp_path / "rotate.request"
    service = TradingService(
        {
            "MASTERTRD_MODE": "PAPER",
            "MASTERTRD_SESSION_STATE": str(state),
            "MASTERTRD_PAPER_ROTATION_REQUEST": str(request),
        },
        clock_ns=lambda: 123,
    )
    with pytest.raises(RuntimeError, match="has not started"):
        service.request_paper_evidence_rotation()

    state.write_text("started", encoding="utf-8")
    assert service.request_paper_evidence_rotation() == request
    assert request.read_text(encoding="utf-8") == "requested_ns=123\n"
    assert service.paper_evidence_rotation_requested() is True
    state.unlink()
    assert service.snapshot()["paper_rotation_requested"] is True


def test_paper_evidence_rotation_request_rejects_non_paper_mode(tmp_path):
    import pytest

    from mastertrd.trading_service import TradingService

    with pytest.raises(RuntimeError, match="requires PAPER mode"):
        TradingService(
            {
                "MASTERTRD_MODE": "TESTNET",
                "MASTERTRD_PAPER_ROTATION_REQUEST": str(tmp_path / "rotate.request"),
            }
        ).request_paper_evidence_rotation()
