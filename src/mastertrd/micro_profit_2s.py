from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from statistics import fmean
from typing import Sequence


@dataclass(frozen=True, slots=True)
class MicroProfit2sReport:
    target_net_usd: float
    window_seconds: float
    window_net_pnl_usd: tuple[float, ...]
    window_count: int
    hit_count: int
    hit_rate: float
    mean_net_usd: float
    min_net_usd: float
    total_net_usd: float
    every_window_passed: bool
    supporting_only: bool
    target_proven: bool

    def __post_init__(self) -> None:
        if not isfinite(float(self.target_net_usd)) or float(self.target_net_usd) <= 0.0:
            raise ValueError("target_net_usd must be positive and finite")
        if not isfinite(float(self.window_seconds)) or float(self.window_seconds) <= 0.0:
            raise ValueError("window_seconds must be positive and finite")
        if self.window_count <= 0 or self.window_count != len(self.window_net_pnl_usd):
            raise ValueError("window_count must match non-empty window PnL evidence")
        if not 0 <= self.hit_count <= self.window_count:
            raise ValueError("hit_count must be inside the window count")
        if not 0.0 <= float(self.hit_rate) <= 1.0:
            raise ValueError("hit_rate must be between zero and one")
        if not all(isfinite(float(value)) for value in self.window_net_pnl_usd):
            raise ValueError("window PnL values must be finite")
        if self.target_proven and (self.supporting_only or not self.every_window_passed):
            raise ValueError("target proof requires non-supporting all-window evidence")


def _decimal(value: object, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def evaluate_micro_profit_windows(
    equity_samples: Sequence[tuple[int, float]],
    *,
    target_net_usd: float,
    window_seconds: float = 2.0,
    synthetic: bool = False,
) -> MicroProfit2sReport:
    """Evaluate strict net-PnL evidence on contiguous non-overlapping windows.

    Samples are account-equity observations taken exactly at each window boundary.
    A target is proven only when every observed window meets the target and the
    source is non-synthetic. Synthetic replays remain supporting evidence even if
    every interval passes.
    """

    if len(equity_samples) < 2:
        raise ValueError("at least two equity samples are required")
    target = _decimal(target_net_usd, name="target_net_usd")
    if target <= 0:
        raise ValueError("target_net_usd must be positive and finite")
    seconds = _decimal(window_seconds, name="window_seconds")
    if seconds <= 0:
        raise ValueError("window_seconds must be positive and finite")
    window_ns_decimal = seconds * Decimal("1000000000")
    if window_ns_decimal != window_ns_decimal.to_integral_value():
        raise ValueError("window_seconds must resolve to whole nanoseconds")
    window_ns = int(window_ns_decimal)

    timestamps: list[int] = []
    equities: list[Decimal] = []
    for timestamp_ns, equity_usd in equity_samples:
        if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int):
            raise ValueError("equity timestamps must be integer nanoseconds")
        timestamps.append(timestamp_ns)
        equities.append(_decimal(equity_usd, name="equity_usd"))

    if any(right <= left for left, right in zip(timestamps, timestamps[1:], strict=False)):
        raise ValueError("equity timestamps must be strictly increasing")
    if any(
        right - left != window_ns
        for left, right in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise ValueError("equity samples must be on exact window boundaries")

    pnl_decimals = tuple(
        right - left
        for left, right in zip(equities, equities[1:], strict=False)
    )
    hits = tuple(value >= target for value in pnl_decimals)
    pnl = tuple(float(value) for value in pnl_decimals)
    hit_count = sum(hits)
    window_count = len(pnl)
    every_window_passed = hit_count == window_count
    supporting_only = bool(synthetic)

    return MicroProfit2sReport(
        target_net_usd=float(target),
        window_seconds=float(seconds),
        window_net_pnl_usd=pnl,
        window_count=window_count,
        hit_count=hit_count,
        hit_rate=hit_count / window_count,
        mean_net_usd=fmean(pnl),
        min_net_usd=min(pnl),
        total_net_usd=float(sum(pnl_decimals, Decimal("0"))),
        every_window_passed=every_window_passed,
        supporting_only=supporting_only,
        target_proven=every_window_passed and not supporting_only,
    )
