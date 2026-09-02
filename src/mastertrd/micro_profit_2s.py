from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from math import ceil, isfinite
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


@dataclass(frozen=True, slots=True)
class MicroProfit2sBacktestResult:
    engine: str
    engine_version: str
    dataset_hash: str
    queue_model: str
    completed_trades: int
    accumulated_fee_usd: float
    equity_samples: tuple[tuple[int, float], ...]
    report: MicroProfit2sReport

    def __post_init__(self) -> None:
        if not all((self.engine, self.engine_version, self.dataset_hash, self.queue_model)):
            raise ValueError("backtest identity fields are required")
        if self.completed_trades < 0:
            raise ValueError("completed_trades cannot be negative")
        if not isfinite(float(self.accumulated_fee_usd)) or self.accumulated_fee_usd < 0.0:
            raise ValueError("accumulated_fee_usd must be non-negative and finite")
        if len(self.equity_samples) < 2:
            raise ValueError("backtest requires at least two equity samples")


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
    """Evaluate strict net-PnL evidence on contiguous non-overlapping windows."""

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


def _nonnegative_finite(value: object, *, name: str) -> float:
    number = float(value)
    if not isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be non-negative and finite")
    return number


def _cancel_working_orders(hbt) -> None:
    values = hbt.orders(0).values()
    order_ids: list[int] = []
    while values.has_next():
        order = values.get()
        if order.cancellable:
            order_ids.append(int(order.order_id))
    for order_id in order_ids:
        rc = hbt.cancel(0, order_id, False)
        if rc not in (0, 1):
            raise RuntimeError("HFT quote cancellation failed")
    hbt.clear_inactive_orders(0)


def run_micro_profit_hftbacktest(
    candidate,
    dataset,
    *,
    latency_profile,
    queue_model: str,
    lot_size: float,
    taker_fee_bps: float,
    extra_slippage_bps: float = 0.0,
) -> MicroProfit2sBacktestResult:
    """Replay the micro-profit strategy through hftbacktest on exact 2-second windows.

    The engine supplies queue effects, order latency and maker/taker fees. Equity is
    marked to the live midpoint and reduced by accumulated engine fees plus an
    explicit turnover-based slippage/adverse-selection penalty. Synthetic datasets
    are always supporting-only and therefore can never prove the profitability target.
    """

    from hftbacktest import BacktestAsset, GTX, HashMapMarketDepthBacktest, LIMIT

    from .data.orderbook import OrderBookDataset
    from .hft_strategy import HftBookState, evaluate_hft_entry_intents
    from .hft_validation import _hftbacktest_events, _tick_size

    if not isinstance(dataset, OrderBookDataset):
        raise TypeError("micro-profit HFT replay requires an OrderBookDataset")
    if candidate.family != "market_making" or str(
        candidate.entry.get("type", candidate.entry.get("kind"))
    ) != "micro_profit_2s":
        raise ValueError("micro-profit HFT replay requires a micro_profit_2s market-making candidate")
    if len(candidate.instruments) != 1:
        raise ValueError("micro-profit HFT replay requires exactly one instrument")
    identity = candidate.instruments[0].upper()
    if dataset.instrument.upper() not in identity or dataset.venue.upper() not in identity:
        raise ValueError("L2 dataset does not match the micro-profit candidate")

    lot = float(lot_size)
    if not isfinite(lot) or lot <= 0.0:
        raise ValueError("lot_size must be positive and finite")
    taker_bps = _nonnegative_finite(taker_fee_bps, name="taker_fee_bps")
    extra_slippage = _nonnegative_finite(extra_slippage_bps, name="extra_slippage_bps")
    maker_bps = _nonnegative_finite(candidate.entry["maker_fee_bps"], name="maker_fee_bps")
    base_slippage = _nonnegative_finite(candidate.entry["slippage_bps"], name="slippage_bps")
    target_net_usd = float(candidate.entry["target_net_usd"])
    max_quote_notional = float(candidate.entry["max_quote_notional_usd"])
    window_seconds = float(candidate.exit.get("timeout_ms", 2000)) / 1000.0
    if window_seconds != 2.0:
        raise ValueError("micro-profit HFT replay requires an exact 2000ms timeout")

    rows = _hftbacktest_events(dataset, latency_profile)
    tick_size = _tick_size(dataset)
    asset = (
        BacktestAsset()
        .data(rows)
        .linear_asset(1.0)
        .no_partial_fill_exchange()
        .trading_value_fee_model(maker_bps / 10_000.0, taker_bps / 10_000.0)
        .constant_order_latency(latency_profile.order_latency_ns, latency_profile.order_latency_ns)
        .tick_size(tick_size)
        .lot_size(lot)
    )
    if queue_model == "risk_adverse_queue_model":
        asset = asset.risk_adverse_queue_model()
    elif queue_model == "power_prob_queue_model":
        asset = asset.power_prob_queue_model(2.0)
    else:
        raise ValueError(f"unsupported queue model: {queue_model}")

    hbt = HashMapMarketDepthBacktest([asset])
    try:
        first_timestamp = (
            dataset.events[0].local_timestamp_ns + latency_profile.feed_latency_ns + 1
        )
        last_timestamp = dataset.events[-1].local_timestamp_ns + latency_profile.feed_latency_ns
        window_ns = int(window_seconds * 1_000_000_000)
        if last_timestamp - first_timestamp < window_ns:
            raise ValueError("L2 dataset is too short for one complete two-second window")
        hbt.elapse(first_timestamp)

        slippage_rate = (base_slippage + extra_slippage) / 10_000.0

        def marked_equity() -> float:
            depth = hbt.depth(0)
            best_bid = float(depth.best_bid)
            best_ask = float(depth.best_ask)
            if not (isfinite(best_bid) and isfinite(best_ask) and best_bid <= best_ask):
                raise RuntimeError("invalid HFT depth while sampling micro-profit equity")
            mid = (best_bid + best_ask) / 2.0
            state = hbt.state_values(0)
            slippage_penalty = float(state.trading_value) * slippage_rate
            return (
                float(state.balance)
                + float(state.position) * mid
                - float(state.fee)
                - slippage_penalty
            )

        equity_samples: list[tuple[int, float]] = [(first_timestamp, marked_equity())]
        next_order_id = 1
        next_boundary = first_timestamp + window_ns

        while next_boundary <= last_timestamp:
            _cancel_working_orders(hbt)
            depth = hbt.depth(0)
            best_bid = float(depth.best_bid)
            best_ask = float(depth.best_ask)
            bid_size = float(depth.best_bid_qty)
            ask_size = float(depth.best_ask_qty)
            state_values = hbt.state_values(0)
            state = HftBookState(
                instrument_id=candidate.instruments[0],
                bid_price=best_bid,
                ask_price=best_ask,
                bid_size=bid_size,
                ask_size=ask_size,
                tick_size=tick_size,
                inventory=float(state_values.position),
                timestamp_ns=int(hbt.current_timestamp),
            )
            intents = evaluate_hft_entry_intents(candidate, {candidate.instruments[0]: state})
            for intent in intents:
                if intent.price is None or not intent.post_only or intent.notional_usd is None:
                    raise RuntimeError("micro-profit HFT replay requires post-only notional quotes")
                raw_quantity = float(intent.notional_usd) / state.midpoint
                quantity = ceil(raw_quantity / lot) * lot
                if quantity * state.midpoint > max_quote_notional * (1.0 + 1e-12):
                    continue
                if intent.direction.value == "LONG":
                    rc = hbt.submit_buy_order(
                        0, next_order_id, float(intent.price), quantity, GTX, LIMIT, False
                    )
                else:
                    rc = hbt.submit_sell_order(
                        0, next_order_id, float(intent.price), quantity, GTX, LIMIT, False
                    )
                if rc not in (0, 1):
                    raise RuntimeError("micro-profit HFT quote submission failed")
                next_order_id += 1

            if hbt.current_timestamp < next_boundary:
                rc = hbt.elapse(next_boundary - hbt.current_timestamp)
                if rc != 0 and hbt.current_timestamp < next_boundary:
                    break
            if hbt.current_timestamp < next_boundary:
                break
            equity_samples.append((next_boundary, marked_equity()))
            next_boundary += window_ns

        if len(equity_samples) < 2:
            raise RuntimeError("micro-profit HFT replay produced no complete evidence window")
        final_state = hbt.state_values(0)
        report = evaluate_micro_profit_windows(
            tuple(equity_samples),
            target_net_usd=target_net_usd,
            window_seconds=window_seconds,
            synthetic=dataset.synthetic,
        )
        return MicroProfit2sBacktestResult(
            engine="hftbacktest",
            engine_version=version("hftbacktest"),
            dataset_hash=dataset.dataset_hash,
            queue_model=queue_model,
            completed_trades=int(final_state.num_trades),
            accumulated_fee_usd=float(final_state.fee),
            equity_samples=tuple(equity_samples),
            report=report,
        )
    finally:
        hbt.close()
