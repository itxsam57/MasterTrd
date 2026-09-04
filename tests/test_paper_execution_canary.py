from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from mastertrd.paper_execution_canary import (
    ExecutionCanaryLane,
    _build_canary_strategy,
    _coalesced_canary_stream,
    _default_lane_deadline_seconds,
    execution_canary_lanes,
    run_paper_execution_canary_matrix,
    validate_execution_canary_result,
)


def _passing_result(lane: ExecutionCanaryLane) -> dict[str, object]:
    sides = {
        "paper-1m-long": ["LONG"],
        "paper-3m-short": ["SHORT"],
        "paper-5m-reversal": ["LONG", "SHORT"],
        "paper-10m-hold-exit": ["LONG"],
    }[lane.name]
    return {
        "lane": lane.name,
        "source_timeframe": lane.source_timeframe,
        "target_minutes": lane.target_minutes,
        "plan": list(lane.plan),
        "real_closed_bars": max(lane.minimum_real_closed_bars, len(lane.plan)),
        "data_healthy": True,
        "missing_closed_bars": 0,
        "recovery_failures": 0,
        "orders_attempted": lane.minimum_orders,
        "orders_allowed": lane.minimum_orders,
        "orders_rejected": 0,
        "observed_sides": sides,
        "closed_positions": lane.minimum_closed_positions,
        "held_source_bars": lane.hold_source_bars,
        "reconciliation_errors": 0,
        "final_flat": True,
        "live_enabled": False,
        "mode": "PAPER",
    }


def test_execution_canary_lanes_cover_fast_long_short_reversal_and_ten_minute_hold() -> None:
    lanes = execution_canary_lanes()
    assert [lane.name for lane in lanes] == [
        "paper-1m-long",
        "paper-3m-short",
        "paper-5m-reversal",
        "paper-10m-hold-exit",
    ]
    assert [(lane.source_timeframe, lane.target_minutes, lane.plan) for lane in lanes] == [
        ("1m", 1, ("LONG", "FLAT")),
        ("3m", 3, ("SHORT", "FLAT")),
        ("5m", 5, ("LONG", "SHORT", "FLAT")),
        ("5m", 10, ("LONG", "HOLD", "FLAT")),
    ]
    assert lanes[-1].hold_source_bars == 1
    assert lanes[-1].minimum_real_closed_bars == 3
    assert all(lane.test_only is True for lane in lanes)
    assert all(lane.counts_as_alpha is False for lane in lanes)
    assert all(lane.live_eligible is False for lane in lanes)


def test_execution_canary_result_requires_real_paper_trade_path() -> None:
    for lane in execution_canary_lanes():
        validate_execution_canary_result(lane, _passing_result(lane))

    lane = execution_canary_lanes()[0]
    bad = _passing_result(lane)
    bad["orders_allowed"] = 0
    with pytest.raises(RuntimeError, match="orders_allowed"):
        validate_execution_canary_result(lane, bad)

    bad = _passing_result(lane)
    bad["final_flat"] = False
    with pytest.raises(RuntimeError, match="final_flat"):
        validate_execution_canary_result(lane, bad)

    bad = _passing_result(lane)
    bad["missing_closed_bars"] = 1
    bad["data_healthy"] = False
    with pytest.raises(RuntimeError, match="data_healthy|missing_closed_bars"):
        validate_execution_canary_result(lane, bad)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("lane", "wrong", "lane identity"),
        ("source_timeframe", "15m", "source_timeframe"),
        ("target_minutes", 99, "target_minutes"),
        ("plan", ["SHORT"], "plan mismatch"),
        ("mode", "LIVE", "mode must be PAPER"),
        ("live_enabled", True, "live_enabled"),
        ("data_healthy", False, "data_healthy"),
        ("missing_closed_bars", 1, "missing_closed_bars"),
        ("recovery_failures", 1, "recovery_failures"),
        ("real_closed_bars", 0, "real_closed_bars"),
        ("orders_attempted", 0, "orders_attempted"),
        ("orders_allowed", 0, "orders_allowed"),
        ("orders_rejected", 1, "orders_rejected"),
        ("closed_positions", 0, "closed_positions"),
        ("reconciliation_errors", 1, "reconciliation_errors"),
        ("final_flat", False, "final_flat"),
        ("observed_sides", None, "observed_sides"),
    ],
)
def test_execution_canary_result_rejects_each_safety_invariant(field, value, message) -> None:
    lane = execution_canary_lanes()[0]
    result = _passing_result(lane)
    result[field] = value
    with pytest.raises(RuntimeError, match=message):
        validate_execution_canary_result(lane, result)


def test_execution_canary_result_rejects_types_hold_and_side_path() -> None:
    lane = execution_canary_lanes()[-1]

    result = _passing_result(lane)
    result["held_source_bars"] = 0
    with pytest.raises(RuntimeError, match="held_source_bars"):
        validate_execution_canary_result(lane, result)

    result = _passing_result(lane)
    result["orders_allowed"] = True
    with pytest.raises(RuntimeError, match="orders_allowed must be an integer"):
        validate_execution_canary_result(lane, result)

    result = _passing_result(lane)
    result["live_enabled"] = 0
    with pytest.raises(RuntimeError, match="live_enabled must be boolean"):
        validate_execution_canary_result(lane, result)

    reversal = execution_canary_lanes()[2]
    result = _passing_result(reversal)
    result["observed_sides"] = ["SHORT", "LONG"]
    with pytest.raises(RuntimeError, match="requested path"):
        validate_execution_canary_result(reversal, result)


def test_execution_canary_stream_coalesces_quotes_before_each_closed_bar() -> None:
    raw = [
        {"event_id": "tick-1", "venue": "BINANCE", "instrument": "ETHUSDT", "timestamp_ms": 1_000, "bid": 100.0, "ask": 101.0, "bid_size": 1.0, "ask_size": 1.0, "last": 100.5, "last_size": 0.0},
        {"event_id": "tick-2", "venue": "BINANCE", "instrument": "ETHUSDT", "timestamp_ms": 2_000, "bid": 101.0, "ask": 102.0, "bid_size": 1.0, "ask_size": 1.0, "last": 101.5, "last_size": 0.0},
        {"event_id": "bar-1", "venue": "BINANCE", "instrument": "ETHUSDT", "timeframe": "5m", "timestamp_ms": 3_000, "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "volume": 10.0},
        {"event_id": "tick-3", "venue": "BINANCE", "instrument": "ETHUSDT", "timestamp_ms": 4_000, "bid": 102.0, "ask": 103.0, "bid_size": 1.0, "ask_size": 1.0, "last": 102.5, "last_size": 0.0},
        {"event_id": "bar-2", "venue": "BINANCE", "instrument": "ETHUSDT", "timeframe": "5m", "timestamp_ms": 5_000, "open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0, "volume": 10.0},
    ]
    events = list(_coalesced_canary_stream(raw))
    assert [event.event_id for event in events] == ["tick-2", "bar-1", "tick-3", "bar-2"]


def test_execution_canary_stream_emits_real_quote_heartbeat_within_reconciliation_window() -> None:
    def tick(event_id: str, timestamp_ms: int, price: float) -> dict[str, object]:
        return {"event_id": event_id, "venue": "BINANCE", "instrument": "ETHUSDT", "timestamp_ms": timestamp_ms, "bid": price, "ask": price + 1.0, "bid_size": 1.0, "ask_size": 1.0, "last": price + 0.5, "last_size": 0.0}

    raw = [
        tick("tick-1", 1_000, 100.0),
        tick("tick-2", 10_000, 101.0),
        tick("tick-3", 32_000, 102.0),
        tick("tick-4", 33_000, 103.0),
        {"event_id": "bar-1", "venue": "BINANCE", "instrument": "ETHUSDT", "timeframe": "5m", "timestamp_ms": 60_000, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 10.0},
    ]
    events = list(_coalesced_canary_stream(raw))
    assert [event.event_id for event in events] == ["tick-3", "tick-4", "bar-1"]


def test_execution_canary_default_deadline_covers_required_closed_bars() -> None:
    for lane in execution_canary_lanes():
        source_minutes = int(lane.source_timeframe.removesuffix("m"))
        required_market_seconds = lane.minimum_real_closed_bars * source_minutes * 60
        assert _default_lane_deadline_seconds(lane) >= required_market_seconds + 180


def test_execution_canary_matrix_rejects_invalid_worker_count() -> None:
    with pytest.raises(TypeError, match="max_workers must be an integer"):
        run_paper_execution_canary_matrix(max_workers=True)
    with pytest.raises(ValueError, match="max_workers must be positive"):
        run_paper_execution_canary_matrix(max_workers=0)


def _strategy_for(lane: ExecutionCanaryLane):
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from mastertrd.risk_runtime import RiskRuntime
    from mastertrd.runtime_factory import _paper_risk_limits

    instrument = TestInstrumentProvider.ethusdt_binance()
    strategy = _build_canary_strategy(
        lane=lane,
        instrument=instrument,
        risk_runtime=RiskRuntime(_paper_risk_limits()),
    )
    return strategy, instrument


def test_execution_canary_strategy_sizes_above_real_venue_minimum() -> None:
    lane = execution_canary_lanes()[0]
    strategy, instrument = _strategy_for(lane)

    with pytest.raises(RuntimeError, match="instrument is unavailable"):
        strategy._canary_order_quantity()
    with pytest.raises(RuntimeError, match="instrument is unavailable"):
        strategy._submit_side("LONG")

    strategy.instrument = instrument
    with pytest.raises(RuntimeError, match="reference price is unavailable"):
        strategy._canary_order_quantity()

    strategy._last_price = 2000.0
    quantity = strategy._canary_order_quantity().as_decimal()
    assert quantity * Decimal("2000") >= Decimal("10.5")

    strategy.instrument = SimpleNamespace(
        min_notional=None,
        make_qty=lambda value: value,
    )
    assert strategy._canary_order_quantity() == Decimal("0.001")


def test_execution_canary_strategy_fail_closed_state_transitions() -> None:
    lane = execution_canary_lanes()[0]
    strategy, instrument = _strategy_for(lane)
    strategy.instrument = instrument

    assert strategy._event_side(SimpleNamespace(side=SimpleNamespace(name="LONG"))) == "LONG"
    assert strategy._event_side(SimpleNamespace(side=SimpleNamespace(name="SHORT"))) == "SHORT"
    assert strategy._event_side(SimpleNamespace(side=SimpleNamespace(name="NONE"))) == "FLAT"

    from nautilus_trader.model.identifiers import InstrumentId

    other = SimpleNamespace(
        instrument_id=InstrumentId.from_str("BTCUSDT.BINANCE"),
        side=SimpleNamespace(name="LONG"),
    )
    strategy.on_position_opened(other)
    strategy.on_position_changed(other)
    strategy.on_position_closed(other)
    assert strategy.observed_sides == []

    invalid = SimpleNamespace(instrument_id=instrument.id, side=SimpleNamespace(name="NONE"))
    with pytest.raises(RuntimeError, match="without a side"):
        strategy.on_position_opened(invalid)

    opened = SimpleNamespace(instrument_id=instrument.id, side=SimpleNamespace(name="LONG"))
    strategy.on_position_opened(opened)
    strategy.on_position_changed(opened)
    assert strategy.observed_sides == ["LONG"]
    assert strategy._position_side == "LONG"

    hold_lane = ExecutionCanaryLane("hold", "1m", 1, ("HOLD",), 1, 1, 0, 0)
    hold, _ = _strategy_for(hold_lane)
    with pytest.raises(RuntimeError, match="cannot HOLD while flat"):
        hold._drive_plan()

    bad_lane = ExecutionCanaryLane("bad", "1m", 1, ("INVALID",), 0, 1, 0, 0)
    bad, _ = _strategy_for(bad_lane)
    with pytest.raises(RuntimeError, match="unsupported execution canary action"):
        bad._drive_plan()

    flat_lane = ExecutionCanaryLane("flat", "1m", 1, ("FLAT",), 0, 1, 0, 0)
    flat, _ = _strategy_for(flat_lane)
    flat._drive_plan()
    assert flat.done is True

    for action in ("LONG", "SHORT"):
        same_lane = ExecutionCanaryLane("same", "1m", 1, (action,), 0, 1, 0, 0)
        same, _ = _strategy_for(same_lane)
        same._position_side = action
        same._drive_plan()
        assert same._cursor == 1


def test_execution_canary_strategy_rejects_unsupported_timeframe() -> None:
    lane = ExecutionCanaryLane("bad-timeframe", "2m", 2, ("FLAT",), 0, 1, 0, 0)
    from mastertrd.risk_runtime import RiskRuntime
    from mastertrd.runtime_factory import _paper_risk_limits

    with pytest.raises(ValueError, match="unsupported execution-canary timeframe"):
        _build_canary_strategy(
            lane=lane,
            instrument=None,
            risk_runtime=RiskRuntime(_paper_risk_limits()),
        )


def test_execution_canary_matrix_writes_one_aggregate_receipt(tmp_path) -> None:
    receipt = tmp_path / "paper-execution-canary.json"
    called: list[str] = []

    def lane_runner(lane: ExecutionCanaryLane) -> dict[str, object]:
        called.append(lane.name)
        return _passing_result(lane)

    result = run_paper_execution_canary_matrix(
        lane_runner=lane_runner,
        receipt_path=receipt,
        max_workers=4,
    )

    assert set(called) == {lane.name for lane in execution_canary_lanes()}
    assert result["mode"] == "PAPER"
    assert result["live_enabled"] is False
    assert result["test_only"] is True
    assert result["counts_as_alpha"] is False
    assert result["live_eligible"] is False
    assert result["all_passed"] is True
    assert [row["lane"] for row in result["lanes"]] == [
        lane.name for lane in execution_canary_lanes()
    ]
    assert json.loads(receipt.read_text(encoding="utf-8")) == result


def test_execution_canary_matrix_fails_closed_and_writes_no_receipt(tmp_path) -> None:
    receipt = tmp_path / "failed.json"

    def lane_runner(lane: ExecutionCanaryLane) -> dict[str, object]:
        result = _passing_result(lane)
        if lane.name == "paper-3m-short":
            result["observed_sides"] = []
        return result

    with pytest.raises(RuntimeError, match="paper-3m-short"):
        run_paper_execution_canary_matrix(
            lane_runner=lane_runner,
            receipt_path=receipt,
            max_workers=4,
        )
    assert not receipt.exists()
