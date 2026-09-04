from __future__ import annotations

import json

import pytest

from mastertrd.paper_execution_canary import (
    ExecutionCanaryLane,
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
        ("5m", 10, ("LONG", "HOLD", "HOLD", "FLAT")),
    ]
    assert lanes[-1].hold_source_bars == 2
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
