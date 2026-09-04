from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionCanaryLane:
    name: str
    source_timeframe: str
    target_minutes: int
    plan: tuple[str, ...]
    hold_source_bars: int
    minimum_real_closed_bars: int
    minimum_orders: int
    minimum_closed_positions: int
    test_only: bool = True
    counts_as_alpha: bool = False
    live_eligible: bool = False


def execution_canary_lanes() -> tuple[ExecutionCanaryLane, ...]:
    return (
        ExecutionCanaryLane("paper-1m-long", "1m", 1, ("LONG", "FLAT"), 0, 2, 2, 1),
        ExecutionCanaryLane("paper-3m-short", "3m", 3, ("SHORT", "FLAT"), 0, 2, 2, 1),
        ExecutionCanaryLane("paper-5m-reversal", "5m", 5, ("LONG", "SHORT", "FLAT"), 0, 3, 3, 2),
        ExecutionCanaryLane("paper-10m-hold-exit", "5m", 10, ("LONG", "HOLD", "HOLD", "FLAT"), 2, 4, 2, 1),
    )


def _integer(result: Mapping[str, object], key: str) -> int:
    value = result.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{key} must be an integer")
    return value


def _boolean(result: Mapping[str, object], key: str) -> bool:
    value = result.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"{key} must be boolean")
    return value


def validate_execution_canary_result(lane: ExecutionCanaryLane, result: Mapping[str, object]) -> None:
    if result.get("lane") != lane.name:
        raise RuntimeError(f"{lane.name}: lane identity mismatch")
    if result.get("source_timeframe") != lane.source_timeframe:
        raise RuntimeError(f"{lane.name}: source_timeframe mismatch")
    if result.get("target_minutes") != lane.target_minutes:
        raise RuntimeError(f"{lane.name}: target_minutes mismatch")
    if tuple(result.get("plan", ())) != lane.plan:
        raise RuntimeError(f"{lane.name}: plan mismatch")
    if result.get("mode") != "PAPER":
        raise RuntimeError(f"{lane.name}: mode must be PAPER")
    if _boolean(result, "live_enabled"):
        raise RuntimeError(f"{lane.name}: live_enabled must be false")
    if not _boolean(result, "data_healthy"):
        raise RuntimeError(f"{lane.name}: data_healthy must be true")
    if _integer(result, "missing_closed_bars") != 0:
        raise RuntimeError(f"{lane.name}: missing_closed_bars must be zero")
    if _integer(result, "recovery_failures") != 0:
        raise RuntimeError(f"{lane.name}: recovery_failures must be zero")
    if _integer(result, "real_closed_bars") < lane.minimum_real_closed_bars:
        raise RuntimeError(f"{lane.name}: real_closed_bars below minimum")
    if _integer(result, "orders_attempted") < lane.minimum_orders:
        raise RuntimeError(f"{lane.name}: orders_attempted below minimum")
    if _integer(result, "orders_allowed") < lane.minimum_orders:
        raise RuntimeError(f"{lane.name}: orders_allowed below minimum")
    if _integer(result, "orders_rejected") != 0:
        raise RuntimeError(f"{lane.name}: orders_rejected must be zero")
    if _integer(result, "closed_positions") < lane.minimum_closed_positions:
        raise RuntimeError(f"{lane.name}: closed_positions below minimum")
    if _integer(result, "held_source_bars") < lane.hold_source_bars:
        raise RuntimeError(f"{lane.name}: held_source_bars below minimum")
    if _integer(result, "reconciliation_errors") != 0:
        raise RuntimeError(f"{lane.name}: reconciliation_errors must be zero")
    if not _boolean(result, "final_flat"):
        raise RuntimeError(f"{lane.name}: final_flat must be true")

    sides_raw = result.get("observed_sides")
    if not isinstance(sides_raw, list) or not all(isinstance(value, str) for value in sides_raw):
        raise RuntimeError(f"{lane.name}: observed_sides must be a string list")
    required_sides = [action for action in lane.plan if action in {"LONG", "SHORT"}]
    cursor = 0
    for observed in sides_raw:
        if cursor < len(required_sides) and observed == required_sides[cursor]:
            cursor += 1
    if cursor != len(required_sides):
        raise RuntimeError(f"{lane.name}: observed_sides did not prove the requested path")


def _write_receipt(path: str | Path, result: Mapping[str, object]) -> None:
    receipt_path = Path(path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = receipt_path.with_name(f".{receipt_path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(dict(result), handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, receipt_path)


LaneRunner = Callable[[ExecutionCanaryLane], dict[str, object]]


def run_paper_execution_canary_lane(lane: ExecutionCanaryLane) -> dict[str, object]:
    raise RuntimeError(f"{lane.name}: real PAPER execution canary runner is not implemented")


def run_paper_execution_canary_matrix(
    *,
    lane_runner: LaneRunner = run_paper_execution_canary_lane,
    receipt_path: str | Path | None = None,
    max_workers: int = 4,
) -> dict[str, object]:
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        raise TypeError("max_workers must be an integer")
    if max_workers <= 0:
        raise ValueError("max_workers must be positive")

    lanes = execution_canary_lanes()
    results: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(lanes))) as pool:
        futures = {pool.submit(lane_runner, lane): lane for lane in lanes}
        for future in as_completed(futures):
            lane = futures[future]
            try:
                result = future.result()
                validate_execution_canary_result(lane, result)
            except Exception as exc:
                for pending in futures:
                    pending.cancel()
                raise RuntimeError(f"{lane.name}: PAPER execution canary failed: {exc}") from exc
            results[lane.name] = dict(result)

    ordered = [results[lane.name] for lane in lanes]
    aggregate: dict[str, Any] = {
        "mode": "PAPER",
        "live_enabled": False,
        "test_only": True,
        "counts_as_alpha": False,
        "live_eligible": False,
        "all_passed": True,
        "lanes": ordered,
    }
    if receipt_path is not None:
        _write_receipt(receipt_path, aggregate)
    return aggregate


if __name__ == "__main__":
    receipt = os.environ.get("MASTERTRD_EXECUTION_CANARY_RECEIPT", "paper-execution-canary-receipt.json")
    print(json.dumps(run_paper_execution_canary_matrix(receipt_path=receipt), sort_keys=True))
