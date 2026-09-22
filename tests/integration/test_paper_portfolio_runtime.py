from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mastertrd.contracts import RuntimeMode
from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.paper_portfolio import JsonPaperPortfolioStore
from mastertrd.runtime import RuntimeConfig
from mastertrd.runtime_factory import build_execution_runtime


START_MS = 1_700_300_000_000
START_NS = START_MS * 1_000_000


def _portfolio_payload(portfolio_id: str, candidates: list[dict[str, object]], *, code_hash: str = "portfolio-code") -> dict[str, object]:
    lock_hash = hashlib.sha256((Path(__file__).resolve().parents[2] / "uv.lock").read_bytes()).hexdigest()
    return {
        "portfolio_id": portfolio_id,
        "code_hash": code_hash,
        "lock_hash": lock_hash,
        "candidates": candidates,
    }


def _candidate(strategy_id: str, instrument: str, fast: int, slow: int) -> dict[str, object]:
    return {
        "strategy_id": strategy_id,
        "family": "trend",
        "style": "day",
        "instruments": [instrument],
        "timeframe": "1m",
        "entry": {
            "kind": "ema_cross",
            "fast_period": fast,
            "slow_period": slow,
            "trade_size": "0.01000",
        },
        "exit": {"kind": "cross_reverse"},
        "data_requirements": ["BAR"],
        "allow_short": False,
    }


def _bar(symbol: str, index: int, close: float) -> dict[str, object]:
    return {
        "event_id": f"{symbol}-{index}",
        "venue": "BINANCE",
        "instrument": symbol,
        "timeframe": "1m",
        "timestamp_ms": START_MS + index * 60_000,
        "open": close - 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "volume": 5.0,
        "spread_bps": 3.0,
        "realized_volatility": 0.01,
    }


def test_portfolio_paper_runtime_uses_one_engine_and_one_risk_path(tmp_path):
    portfolio_path = tmp_path / "portfolio.json"
    state_path = tmp_path / "portfolio-state.json"
    feed_path = tmp_path / "feed.jsonl"
    portfolio_path.write_text(
        json.dumps(
            _portfolio_payload(
                "paper-default",
                [
                    _candidate("paper-eth", "ETHUSDT.BINANCE", 3, 8),
                    _candidate("paper-btc", "BTCUSDT.BINANCE", 4, 9),
                ],
            )
        ),
        encoding="utf-8",
    )
    events = []
    for index in range(20):
        events.append(_bar("ETHUSDT", index, 2000.0 + index * 4.0))
        events.append(_bar("BTCUSDT", index, 60000.0 + index * 50.0))
    feed_path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")

    runtime = build_execution_runtime(
        RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False),
        {
            "MASTERTRD_PORTFOLIO_MANIFEST": str(portfolio_path),
            "MASTERTRD_SESSION_STATE": str(state_path),
            "MASTERTRD_CODE_HASH": "portfolio-code",
            "MASTERTRD_PAPER_START_NS": str(START_NS),
            "MASTERTRD_PUBLIC_FEED_FIXTURE": str(feed_path),
        },
    )

    assert isinstance(runtime, ExecutionRuntime)
    execution = runtime._dispatch.__self__
    assert len(execution.strategies) == 2
    assert len({id(strategy.risk_runtime) for strategy in execution.strategies}) == 1

    report = runtime.run()
    assert report.processed_events == len(events)
    assert report.reconciliation_errors == 0
    assert report.system_killed is False

    restored = JsonPaperPortfolioStore(state_path).load()
    assert restored.portfolio_id == "paper-default"
    assert set(restored.strategy_ids) == {"paper-eth", "paper-btc"}
    assert all(restored.journal(strategy_id).has_event("ETHUSDT-19") for strategy_id in restored.strategy_ids)
    assert restored.execution_state_checkpoint is not None


def test_portfolio_manifest_fails_closed_on_duplicate_strategy_or_mixed_timeframe(tmp_path):
    import pytest

    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(
        json.dumps(
            _portfolio_payload(
                "paper-default",
                [
                    _candidate("same", "ETHUSDT.BINANCE", 3, 8),
                    _candidate("same", "BTCUSDT.BINANCE", 4, 9),
                ],
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="strategy identities must be unique"):
        build_execution_runtime(
            RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False),
            {
                "MASTERTRD_PORTFOLIO_MANIFEST": str(portfolio_path),
                "MASTERTRD_SESSION_STATE": str(tmp_path / "state.json"),
                "MASTERTRD_CODE_HASH": "portfolio-code",
            },
        )


def test_portfolio_paper_runtime_supports_mixed_timeframes(tmp_path):
    portfolio_path = tmp_path / "portfolio-mixed.json"
    state_path = tmp_path / "portfolio-mixed-state.json"
    feed_path = tmp_path / "mixed-feed.jsonl"
    eth = _candidate("paper-eth-1m", "ETHUSDT.BINANCE", 3, 8)
    btc = {**_candidate("paper-btc-5m", "BTCUSDT.BINANCE", 4, 9), "timeframe": "5m"}
    portfolio_path.write_text(
        json.dumps(
            _portfolio_payload("paper-mixed", [eth, btc])
        ),
        encoding="utf-8",
    )
    events = []
    for index in range(12):
        events.append(_bar("ETHUSDT", index, 2000.0 + index * 3.0))
        btc_bar = _bar("BTCUSDT", index * 5, 60000.0 + index * 100.0)
        btc_bar["timeframe"] = "5m"
        events.append(btc_bar)
    feed_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    runtime = build_execution_runtime(
        RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False),
        {
            "MASTERTRD_PORTFOLIO_MANIFEST": str(portfolio_path),
            "MASTERTRD_SESSION_STATE": str(state_path),
            "MASTERTRD_CODE_HASH": "portfolio-code",
            "MASTERTRD_PAPER_START_NS": str(START_NS),
            "MASTERTRD_PUBLIC_FEED_FIXTURE": str(feed_path),
        },
    )

    execution = runtime._dispatch.__self__
    assert {strategy.genome.timeframe for strategy in execution.strategies} == {"1m", "5m"}
    report = runtime.run()
    assert report.processed_events == len(events)
    assert report.reconciliation_errors == 0


def test_portfolio_manifest_rejects_stale_code_and_lock_identity(tmp_path):
    import pytest

    candidates = [
        _candidate("paper-eth", "ETHUSDT.BINANCE", 3, 8),
        _candidate("paper-btc", "BTCUSDT.BINANCE", 4, 9),
    ]
    stale_code = tmp_path / "stale-code.json"
    stale_code.write_text(
        json.dumps(
            _portfolio_payload("stale-code", candidates, code_hash="old-code")
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="code_hash"):
        build_execution_runtime(
            RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False),
            {
                "MASTERTRD_PORTFOLIO_MANIFEST": str(stale_code),
                "MASTERTRD_SESSION_STATE": str(tmp_path / "state-code.json"),
                "MASTERTRD_CODE_HASH": "current-code",
            },
        )

    stale_lock = tmp_path / "stale-lock.json"
    payload = _portfolio_payload("stale-lock", candidates, code_hash="current-code")
    payload["lock_hash"] = "0" * 64
    stale_lock.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="lock_hash"):
        build_execution_runtime(
            RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False),
            {
                "MASTERTRD_PORTFOLIO_MANIFEST": str(stale_lock),
                "MASTERTRD_SESSION_STATE": str(tmp_path / "state-lock.json"),
                "MASTERTRD_CODE_HASH": "current-code",
            },
        )


def test_portfolio_paper_runtime_rotates_each_strategy_into_forward_evidence(tmp_path):
    from mastertrd.paper_archive import JsonPaperReportArchive

    portfolio_path = tmp_path / "portfolio.json"
    state_path = tmp_path / "portfolio-state.json"
    feed_path = tmp_path / "feed.jsonl"
    archive_path = tmp_path / "paper-reports.json"
    history_dir = tmp_path / "paper-history"
    rotation_request = tmp_path / "ROTATE"
    candidates = [
        _candidate("paper-eth", "ETHUSDT.BINANCE", 3, 8),
        _candidate("paper-btc", "BTCUSDT.BINANCE", 4, 9),
    ]
    portfolio_path.write_text(
        json.dumps(_portfolio_payload("paper-forward", candidates)),
        encoding="utf-8",
    )
    events = [
        _bar("ETHUSDT", 0, 2000.0),
        _bar("BTCUSDT", 0, 60000.0),
        _bar("ETHUSDT", 1, 2001.0),
        _bar("BTCUSDT", 1, 60010.0),
    ]
    feed_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    rotation_request.write_text("rotate\n", encoding="utf-8")

    runtime = build_execution_runtime(
        RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False),
        {
            "MASTERTRD_PORTFOLIO_MANIFEST": str(portfolio_path),
            "MASTERTRD_SESSION_STATE": str(state_path),
            "MASTERTRD_CODE_HASH": "portfolio-code",
            "MASTERTRD_PAPER_START_NS": str(START_NS),
            "MASTERTRD_PUBLIC_FEED_FIXTURE": str(feed_path),
            "MASTERTRD_PAPER_ARCHIVE": str(archive_path),
            "MASTERTRD_PAPER_HISTORY_DIR": str(history_dir),
            "MASTERTRD_PAPER_ROTATION_REQUEST": str(rotation_request),
        },
    )
    initial = {
        strategy_id: runtime._journal.journal(strategy_id).session_id
        for strategy_id in runtime._journal.strategy_ids
    }

    report = runtime.run()

    assert report.session_rotations == 1
    assert rotation_request.exists() is False
    current = JsonPaperPortfolioStore(state_path).load()
    assert set(current.strategy_ids) == set(initial)
    assert all(
        current.journal(strategy_id).session_id != initial[strategy_id]
        for strategy_id in current.strategy_ids
    )
    archives = sorted(tmp_path.glob("paper-reports-*.json"))
    assert len(archives) == 2
    archived = [
        report
        for path in archives
        for report in JsonPaperReportArchive(path).load()
    ]
    assert {item.strategy_id for item in archived} == set(initial)
    assert {item.session_id for item in archived} == set(initial.values())
    assert all(item.provenance_verified for item in archived)
    assert len(list(history_dir.glob("*/*.json"))) == 2
