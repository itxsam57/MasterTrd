import json

from mastertrd.binance_stream import BinancePublicBookTickerSource
from mastertrd.contracts import RuntimeMode
from mastertrd.execution_runtime import ExecutionRuntime
from mastertrd.runtime import RuntimeConfig
from mastertrd.runtime_factory import build_execution_runtime


START_MS = 1_700_200_000_000
START_NS = START_MS * 1_000_000


def _candidate_manifest() -> dict[str, object]:
    return {
        "strategy_id": "paper-factory-trend-1",
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


def _feed_event() -> dict[str, object]:
    return {
        "event_id": "binance-fixture-1",
        "venue": "BINANCE",
        "instrument": "ETHUSDT",
        "timeframe": "1m",
        "timestamp_ms": START_MS,
        "open": 2_000.0,
        "high": 2_010.0,
        "low": 1_995.0,
        "close": 2_005.0,
        "volume": 10.0,
        "spread_bps": 5.0,
        "realized_volatility": 0.02,
    }


def _trend_feed() -> list[dict[str, object]]:
    prices = (
        [2100 - i * 2 for i in range(15)]
        + [2070 + i * 5 for i in range(20)]
        + [2165 - i * 6 for i in range(20)]
    )
    events: list[dict[str, object]] = []
    previous_close = float(prices[0] + 1)
    for index, close in enumerate(prices):
        close_value = float(close)
        events.append(
            {
                "event_id": f"binance-trend-{index:03d}",
                "venue": "BINANCE",
                "instrument": "ETHUSDT",
                "timeframe": "1m",
                "timestamp_ms": START_MS + index * 60_000,
                "open": previous_close,
                "high": max(previous_close, close_value) + 1.0,
                "low": min(previous_close, close_value) - 1.0,
                "close": close_value,
                "volume": 1.0,
                "spread_bps": 5.0,
                "realized_volatility": 0.02,
            }
        )
        previous_close = close_value
    return events


def _factory_environment(candidate_path, feed_path, session_path) -> dict[str, str]:
    return {
        "MASTERTRD_CANDIDATE_MANIFEST": str(candidate_path),
        "MASTERTRD_SESSION_STATE": str(session_path),
        "MASTERTRD_CODE_HASH": "code-v2",
        "MASTERTRD_PAPER_START_NS": str(START_NS),
        "MASTERTRD_SESSION_NONCE": "fixture-paper-1",
        "MASTERTRD_PUBLIC_FEED_FIXTURE": str(feed_path),
    }


def _public_stream_environment(candidate_path, session_path) -> dict[str, str]:
    return {
        "MASTERTRD_CANDIDATE_MANIFEST": str(candidate_path),
        "MASTERTRD_SESSION_STATE": str(session_path),
        "MASTERTRD_CODE_HASH": "code-v2",
        "MASTERTRD_PAPER_START_NS": str(START_NS),
        "MASTERTRD_SESSION_NONCE": "public-paper-1",
    }


def test_paper_factory_builds_persistent_runtime_from_candidate_and_public_feed_fixture(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    feed_path = tmp_path / "public-feed.jsonl"
    session_path = tmp_path / "paper-session.json"
    candidate_path.write_text(json.dumps(_candidate_manifest()), encoding="utf-8")
    feed_path.write_text(json.dumps(_feed_event()) + "\n", encoding="utf-8")

    runtime = RuntimeConfig(
        mode=RuntimeMode.PAPER,
        live_trading_enabled=False,
        oracle_enabled=False,
    )
    built = build_execution_runtime(runtime, _factory_environment(candidate_path, feed_path, session_path))

    assert isinstance(built, ExecutionRuntime)
    report = built.run()
    assert report.processed_events == 1
    assert report.duplicate_events == 0
    assert report.reconciliation_checks == 2
    assert report.reconciliation_errors == 0
    assert report.system_killed is False
    assert session_path.exists()

    persisted = json.loads(session_path.read_text(encoding="utf-8"))
    payload = persisted["payload"]
    assert payload["receipt"]["strategy_id"] == "paper-factory-trend-1"
    event_ids = {event["event_id"] for event in payload["events"]}
    assert "binance-fixture-1" in event_ids


def test_paper_factory_routes_public_feed_through_real_nautilus_strategy_and_records_close(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    feed_path = tmp_path / "public-feed-trend.jsonl"
    session_path = tmp_path / "paper-session-trend.json"
    candidate_path.write_text(json.dumps(_candidate_manifest()), encoding="utf-8")
    feed_path.write_text(
        "".join(json.dumps(event) + "\n" for event in _trend_feed()),
        encoding="utf-8",
    )

    runtime = RuntimeConfig(
        mode=RuntimeMode.PAPER,
        live_trading_enabled=False,
        oracle_enabled=False,
    )
    built = build_execution_runtime(runtime, _factory_environment(candidate_path, feed_path, session_path))
    report = built.run()

    assert report.processed_events == len(_trend_feed())
    assert report.reconciliation_errors == 0
    assert report.system_killed is False

    persisted = json.loads(session_path.read_text(encoding="utf-8"))["payload"]
    closed = [event for event in persisted["events"] if event["kind"] == "closed_trade"]
    assert closed, "PAPER runtime must persist a real Nautilus PositionClosed event"


def test_paper_factory_defaults_to_checked_in_binance_public_stream_without_fixture(tmp_path):
    candidate_path = tmp_path / "candidate.json"
    session_path = tmp_path / "paper-session-public.json"
    candidate_path.write_text(json.dumps(_candidate_manifest()), encoding="utf-8")

    runtime = RuntimeConfig(
        mode=RuntimeMode.PAPER,
        live_trading_enabled=False,
        oracle_enabled=False,
    )
    built = build_execution_runtime(runtime, _public_stream_environment(candidate_path, session_path))

    assert isinstance(built, ExecutionRuntime)
    assert isinstance(built._stream._source, BinancePublicBookTickerSource)
    assert built._stream._source.symbols == ("ETHUSDT",)
