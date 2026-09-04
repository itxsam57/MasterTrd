import json
from datetime import datetime, timezone

import pytest

import mastertrd.runtime_factory as runtime_factory_module
from mastertrd.binance_stream import BinancePublicMarketSource
from mastertrd.contracts import MarketBar, RuntimeMode
from mastertrd.nautilus_paper import fixture_binance_spot_instrument
from mastertrd.runtime import RuntimeConfig
from mastertrd.runtime_factory import build_execution_runtime


def _candidate_manifest() -> dict[str, object]:
    return {
        "strategy_id": "paper-completeness-anchor-1",
        "family": "trend",
        "style": "day",
        "instruments": ["ETHUSDT.BINANCE"],
        "timeframe": "1m",
        "entry": {
            "kind": "ema_cross",
            "fast_period": 3,
            "slow_period": 8,
            "trade_size": "0.10000",
        },
        "exit": {"kind": "cross_reverse"},
        "data_requirements": ["BAR"],
        "allow_short": False,
    }


def _bootstrap_history(*, include_close_identity: bool = True) -> tuple[MarketBar, ...]:
    bars: list[MarketBar] = []
    for index in range(8):
        close_ms = (index + 1) * 60_000 - 1
        extras: dict[str, object] = {"bootstrap": True}
        if include_close_identity:
            extras["source_kline_close_ms"] = close_ms
        bars.append(
            MarketBar(
                timestamp=datetime.fromtimestamp(close_ms / 1_000.0, tz=timezone.utc),
                venue="BINANCE",
                instrument="ETHUSDT.BINANCE",
                timeframe="1m",
                open=2_000.0 + index,
                high=2_010.0 + index,
                low=1_990.0 + index,
                close=2_005.0 + index,
                volume=10.0,
                extras=extras,
            )
        )
    return tuple(bars)


def _environment(candidate_path, session_path) -> dict[str, str]:
    return {
        "MASTERTRD_CANDIDATE_MANIFEST": str(candidate_path),
        "MASTERTRD_SESSION_STATE": str(session_path),
        "MASTERTRD_CODE_HASH": "code-completeness-v1",
        "MASTERTRD_SESSION_NONCE": "public-paper-completeness-1",
    }


def _patch_public_dependencies(monkeypatch, history: tuple[MarketBar, ...]) -> None:
    monkeypatch.setattr(
        runtime_factory_module,
        "load_public_binance_spot_instrument",
        lambda instrument_id: fixture_binance_spot_instrument(instrument_id),
    )
    monkeypatch.setattr(
        runtime_factory_module,
        "load_public_binance_bar_history",
        lambda *_args, **_kwargs: history,
    )


def test_real_paper_factory_anchors_completeness_to_first_bar_after_bootstrap(tmp_path, monkeypatch):
    candidate_path = tmp_path / "candidate.json"
    session_path = tmp_path / "paper-session.json"
    candidate_path.write_text(json.dumps(_candidate_manifest()), encoding="utf-8")
    history = _bootstrap_history()
    _patch_public_dependencies(monkeypatch, history)

    built = build_execution_runtime(
        RuntimeConfig(
            mode=RuntimeMode.PAPER,
            live_trading_enabled=False,
            oracle_enabled=False,
        ),
        _environment(candidate_path, session_path),
    )

    source = built._stream._source
    assert isinstance(source, BinancePublicMarketSource)
    assert source.completeness_snapshot is not None
    assert source._completeness is not None
    assert source._completeness._first_expected_start_ms == 480_000
    assert source.completeness_snapshot.expected_closed_bars == 0

    execution = built._dispatch.__self__
    telemetry = execution.strategy_telemetry()
    assert telemetry["expected_closed_bars"] == 0
    assert telemetry["ws_closed_bars"] == 0
    assert telemetry["rest_recovered_bars"] == 0
    assert telemetry["missing_closed_bars"] == 0
    assert telemetry["recovery_failures"] == 0
    assert telemetry["last_closed_bar_ms"] is None
    assert telemetry["last_expected_close_ms"] is None
    assert telemetry["last_recovery_error"] is None
    assert telemetry["data_healthy"] is True
    built.close()


def test_real_paper_factory_fails_before_session_creation_without_bootstrap_close_identity(
    tmp_path,
    monkeypatch,
):
    candidate_path = tmp_path / "candidate.json"
    session_path = tmp_path / "paper-session.json"
    candidate_path.write_text(json.dumps(_candidate_manifest()), encoding="utf-8")
    _patch_public_dependencies(
        monkeypatch,
        _bootstrap_history(include_close_identity=False),
    )

    with pytest.raises(RuntimeError, match="bootstrap.*closed-bar identity"):
        build_execution_runtime(
            RuntimeConfig(
                mode=RuntimeMode.PAPER,
                live_trading_enabled=False,
                oracle_enabled=False,
            ),
            _environment(candidate_path, session_path),
        )

    assert session_path.exists() is False
