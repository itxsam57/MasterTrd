import json

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
    built = build_execution_runtime(
        runtime,
        {
            "MASTERTRD_CANDIDATE_MANIFEST": str(candidate_path),
            "MASTERTRD_SESSION_STATE": str(session_path),
            "MASTERTRD_CODE_HASH": "code-v2",
            "MASTERTRD_PAPER_START_NS": str(START_NS),
            "MASTERTRD_SESSION_NONCE": "fixture-paper-1",
            "MASTERTRD_PUBLIC_FEED_FIXTURE": str(feed_path),
        },
    )

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
