from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import version
import json
from math import isfinite

from .data.orderbook import OrderBookDataset
from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class HftLatencyProfile:
    feed_latency_ns: int
    order_latency_ns: int

    def __post_init__(self) -> None:
        if self.feed_latency_ns < 0 or self.order_latency_ns < 0:
            raise ValueError("HFT latencies cannot be negative")


@dataclass(frozen=True, slots=True)
class HftStressPolicy:
    min_completed_trades: int
    min_stressed_return: float
    max_queue_degradation: float
    max_feed_latency_degradation: float
    max_order_latency_degradation: float
    max_spread_degradation: float

    def __post_init__(self) -> None:
        if self.min_completed_trades <= 0:
            raise ValueError("min_completed_trades must be positive")
        numeric = (
            self.min_stressed_return,
            self.max_queue_degradation,
            self.max_feed_latency_degradation,
            self.max_order_latency_degradation,
            self.max_spread_degradation,
        )
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("HFT stress policy values must be finite")
        degradation_limits = numeric[1:]
        if not all(0.0 <= value <= 1.0 for value in degradation_limits):
            raise ValueError("HFT degradation limits must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class HftStressReport:
    strategy_id: str
    genome_hash: str
    dataset_hash: str
    code_hash: str
    engine_version: str
    queue_model: str
    baseline_return: float
    queue_model_return: float
    feed_latency_stress_return: float
    order_latency_stress_return: float
    spread_stress_return: float
    completed_trades: int

    def __post_init__(self) -> None:
        identity = (
            self.strategy_id,
            self.genome_hash,
            self.dataset_hash,
            self.code_hash,
            self.engine_version,
            self.queue_model,
        )
        if not all(identity):
            raise ValueError("HFT report identity fields and queue_model are required")
        metrics = (
            self.baseline_return,
            self.queue_model_return,
            self.feed_latency_stress_return,
            self.order_latency_stress_return,
            self.spread_stress_return,
        )
        if not all(isfinite(float(value)) for value in metrics):
            raise ValueError("HFT report returns must be finite")
        if self.completed_trades < 0:
            raise ValueError("completed_trades cannot be negative")


def _degradation(baseline: float, stressed: float) -> float:
    if baseline <= 0.0:
        return 0.0 if stressed >= baseline else 1.0
    return max(0.0, (baseline - stressed) / baseline)


def _dataset_hash(report: HftStressReport) -> str:
    encoded = json.dumps(asdict(report), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def hft_stress_evidence(
    candidate: StrategyGenome,
    report: HftStressReport,
    policy: HftStressPolicy,
) -> tuple[ValidationEvidence, ...]:
    if report.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if report.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")
    if not report.queue_model:
        raise ValueError("queue_model is required")

    common_pass = report.completed_trades >= policy.min_completed_trades
    dataset_hash = _dataset_hash(report)
    scenarios = (
        (
            "hft_queue_model",
            report.queue_model_return,
            policy.max_queue_degradation,
        ),
        (
            "hft_feed_latency_stress",
            report.feed_latency_stress_return,
            policy.max_feed_latency_degradation,
        ),
        (
            "hft_order_latency_stress",
            report.order_latency_stress_return,
            policy.max_order_latency_degradation,
        ),
        (
            "spread_stress",
            report.spread_stress_return,
            policy.max_spread_degradation,
        ),
    )

    records: list[ValidationEvidence] = []
    for evidence_type, stressed_return, max_degradation in scenarios:
        degradation = _degradation(report.baseline_return, stressed_return)
        passed = (
            common_pass
            and stressed_return >= policy.min_stressed_return
            and degradation <= max_degradation
        )
        records.append(
            ValidationEvidence(
                strategy_id=candidate.strategy_id,
                genome_hash=candidate.genome_hash,
                evidence_type=evidence_type,
                dataset_hash=dataset_hash,
                code_hash=report.code_hash,
                engine="hftbacktest",
                engine_version=report.engine_version,
                passed=passed,
                metrics={
                    "baseline_return": report.baseline_return,
                    "stressed_return": stressed_return,
                    "return_degradation": degradation,
                    "completed_trades": float(report.completed_trades),
                },
                supporting_only=True,
            )
        )
    return tuple(records)


def _hftbacktest_events(dataset: OrderBookDataset, latency_profile: HftLatencyProfile):
    import numpy as np
    from hftbacktest import (
        BUY_EVENT,
        DEPTH_EVENT,
        EXCH_EVENT,
        LOCAL_EVENT,
        SELL_EVENT,
        TRADE_EVENT,
    )
    from hftbacktest.binding import event_dtype

    event_count = sum(len(event.bids) + len(event.asks) + len(event.trades) for event in dataset.events)
    rows = np.zeros(event_count, dtype=event_dtype)
    index = 0

    def write(flag: int, exchange_ts: int, local_ts: int, price: float, size: float) -> None:
        nonlocal index
        rows[index]["ev"] = flag
        rows[index]["exch_ts"] = exchange_ts
        rows[index]["local_ts"] = local_ts + latency_profile.feed_latency_ns
        rows[index]["px"] = price
        rows[index]["qty"] = size
        index += 1

    bid_depth = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
    ask_depth = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
    buy_trade = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
    sell_trade = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT

    for event in dataset.events:
        for level in event.bids:
            write(bid_depth, event.exchange_timestamp_ns, event.local_timestamp_ns, level.price, level.size)
        for level in event.asks:
            write(ask_depth, event.exchange_timestamp_ns, event.local_timestamp_ns, level.price, level.size)
        for trade in event.trades:
            flag = buy_trade if trade.side == "BUY" else sell_trade
            write(flag, event.exchange_timestamp_ns, event.local_timestamp_ns, trade.price, trade.size)
    return rows


def _tick_size(dataset: OrderBookDataset) -> float:
    prices = sorted({
        round(level.price, 12)
        for event in dataset.events
        for level in (*event.bids, *event.asks)
    })
    differences = [round(right - left, 12) for left, right in zip(prices, prices[1:]) if right > left]
    return min(differences) if differences else max(prices[0] * 1e-8, 1e-8)


def _run_real_l2_replay(
    dataset: OrderBookDataset,
    latency_profile: HftLatencyProfile,
    queue_model: str,
) -> tuple[int, int, float, float]:
    from hftbacktest import BacktestAsset, GTX, HashMapMarketDepthBacktest, LIMIT

    rows = _hftbacktest_events(dataset, latency_profile)
    asset = (
        BacktestAsset()
        .data(rows)
        .linear_asset(1.0)
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0)
        .constant_order_latency(latency_profile.order_latency_ns, latency_profile.order_latency_ns)
        .tick_size(_tick_size(dataset))
        .lot_size(0.001)
    )
    if queue_model == "risk_adverse_queue_model":
        asset = asset.risk_adverse_queue_model()
    elif queue_model == "power_prob_queue_model":
        asset = asset.power_prob_queue_model(2.0)
    else:
        raise ValueError(f"unsupported queue model: {queue_model}")

    hbt = HashMapMarketDepthBacktest([asset])
    try:
        first_local_ts = dataset.events[0].local_timestamp_ns + latency_profile.feed_latency_ns
        hbt.elapse(first_local_ts + 1)
        order_id = 1

        for event in dataset.events[1:]:
            event_local_ts = event.local_timestamp_ns + latency_profile.feed_latency_ns
            if event.trades:
                lead = latency_profile.order_latency_ns + 1_000
                submit_at = max(hbt.current_timestamp, event_local_ts - lead)
                if hbt.current_timestamp < submit_at:
                    hbt.elapse(submit_at - hbt.current_timestamp)

                depth = hbt.depth(0)
                best_bid = float(depth.best_bid)
                best_ask = float(depth.best_ask)
                if not (isfinite(best_bid) and isfinite(best_ask) and best_bid <= best_ask):
                    raise RuntimeError("invalid HFT depth before historical trade replay")

                for trade in event.trades:
                    if trade.side == "SELL":
                        rc = hbt.submit_buy_order(0, order_id, best_bid, 0.01, GTX, LIMIT, False)
                    else:
                        rc = hbt.submit_sell_order(0, order_id, best_ask, 0.01, GTX, LIMIT, False)
                    if rc != 0:
                        raise RuntimeError("historical L2 quote submission failed")
                    order_id += 1

            if hbt.current_timestamp < event_local_ts + 1:
                hbt.elapse(event_local_ts + 1 - hbt.current_timestamp)
            hbt.clear_inactive_orders(0)

        state = hbt.state_values(0)
        depth = hbt.depth(0)
        best_bid = float(depth.best_bid)
        best_ask = float(depth.best_ask)
        if not (isfinite(best_bid) and isfinite(best_ask) and best_bid <= best_ask):
            raise RuntimeError("historical L2 replay ended with invalid depth")
        market_trade_count = sum(len(event.trades) for event in dataset.events)
        return int(state.num_trades), market_trade_count, best_bid, best_ask
    finally:
        hbt.close()


def validate_hft_candidate(
    candidate: StrategyGenome,
    dataset: OrderBookDataset,
    *,
    latency_profile: HftLatencyProfile,
    queue_model: str,
) -> ValidationEvidence:
    if not isinstance(dataset, OrderBookDataset):
        raise TypeError("HFT validation requires an OrderBookDataset")

    instrument = dataset.instrument.upper()
    venue = dataset.venue.upper()
    if not any(instrument in item.upper() and venue in item.upper() for item in candidate.instruments):
        raise ValueError("historical L2 dataset does not match candidate instrument and venue")

    completed_trades, market_trade_count, best_bid, best_ask = _run_real_l2_replay(
        dataset,
        latency_profile,
        queue_model,
    )
    passed = completed_trades > 0 and market_trade_count > 0
    code_hash = hashlib.sha256(b"mastertrd:hft-real-l2-validator:v1").hexdigest()
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="hft_real_l2",
        dataset_hash=dataset.dataset_hash,
        code_hash=code_hash,
        engine="hftbacktest",
        engine_version=version("hftbacktest"),
        passed=passed,
        metrics={
            "completed_trades": float(completed_trades),
            "market_trade_count": float(market_trade_count),
            "event_count": float(len(dataset.events)),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "feed_latency_ns": float(latency_profile.feed_latency_ns),
            "order_latency_ns": float(latency_profile.order_latency_ns),
        },
        supporting_only=dataset.synthetic,
    )
