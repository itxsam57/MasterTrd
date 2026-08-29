from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from math import isfinite

from .genome import StrategyGenome
from .hft_validation import HftStressReport


@dataclass(frozen=True, slots=True)
class HftEngineProbeResult:
    engine: str
    engine_version: str
    event_count: int
    best_bid: float
    best_ask: float
    processed: bool


@dataclass(frozen=True, slots=True)
class _ScenarioResult:
    normalized_return: float
    completed_trades: int


def _validate_stress_request(dataset_hash: str, code_hash: str, cycles: int) -> None:
    if not dataset_hash:
        raise ValueError("dataset_hash is required")
    if not code_hash:
        raise ValueError("code_hash is required")
    if cycles <= 0:
        raise ValueError("cycles must be positive")


def _synthetic_l2_events(*, cycles: int, ask_price: float, feed_latency_ns: int):
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

    events_per_cycle = 4
    events = np.zeros(2 + cycles * events_per_cycle, dtype=event_dtype)

    def write(index: int, flag: int, exch_ts: int, price: float, qty: float) -> None:
        events[index]["ev"] = flag
        events[index]["exch_ts"] = exch_ts
        events[index]["local_ts"] = exch_ts + feed_latency_ns
        events[index]["px"] = price
        events[index]["qty"] = qty

    bid_depth = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
    ask_depth = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
    sell_trade = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
    buy_trade = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT

    write(0, bid_depth, 1_000_000, 100.0, 0.10)
    write(1, ask_depth, 1_100_000, ask_price, 0.10)
    index = 2
    for cycle in range(cycles):
        base = 5_000_000 + cycle * 10_000_000
        write(index, bid_depth, base, 100.0, 0.10)
        write(index + 1, ask_depth, base + 100_000, ask_price, 0.10)
        write(index + 2, sell_trade, base + 3_000_000, 100.0, 10.0)
        write(index + 3, buy_trade, base + 6_000_000, ask_price, 10.0)
        index += events_per_cycle
    return events


def _run_hft_scenario(
    *,
    cycles: int,
    ask_price: float,
    queue_model: str,
    feed_latency_ns: int = 0,
    order_latency_ns: int = 0,
) -> _ScenarioResult:
    from hftbacktest import BacktestAsset, GTX, HashMapMarketDepthBacktest, LIMIT

    events = _synthetic_l2_events(
        cycles=cycles,
        ask_price=ask_price,
        feed_latency_ns=feed_latency_ns,
    )
    asset = (
        BacktestAsset()
        .data(events)
        .linear_asset(1.0)
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0)
        .constant_order_latency(order_latency_ns, order_latency_ns)
        .tick_size(0.1)
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
        first_quote_local_ts = 1_100_000 + feed_latency_ns
        hbt.elapse(first_quote_local_ts + 100_000)
        for cycle in range(cycles):
            base = 5_000_000 + cycle * 10_000_000 + feed_latency_ns
            quote_ready = base + 200_000
            if hbt.current_timestamp < quote_ready:
                hbt.elapse(quote_ready - hbt.current_timestamp)

            depth = hbt.depth(0)
            bid = float(depth.best_bid)
            ask = float(depth.best_ask)
            if not (isfinite(bid) and isfinite(ask) and bid <= ask):
                raise RuntimeError("invalid HFT depth before quote placement")

            buy_id = cycle * 2 + 1
            sell_id = cycle * 2 + 2
            buy_rc = hbt.submit_buy_order(0, buy_id, bid, 0.01, GTX, LIMIT, False)
            sell_rc = hbt.submit_sell_order(0, sell_id, ask, 0.01, GTX, LIMIT, False)
            if buy_rc != 0 or sell_rc != 0:
                raise RuntimeError("HFT quote submission failed")

            cycle_done = base + 7_000_000
            if hbt.current_timestamp < cycle_done:
                hbt.elapse(cycle_done - hbt.current_timestamp)
            hbt.clear_inactive_orders(0)

        state = hbt.state_values(0)
        completed_trades = int(state.num_trades)
        final_depth = hbt.depth(0)
        mid = (float(final_depth.best_bid) + float(final_depth.best_ask)) / 2.0
        equity = float(state.balance) + float(state.position) * mid
        normalized_return = equity / max(1.0, float(state.trading_value))
        if not isfinite(normalized_return):
            raise RuntimeError("HFT scenario produced non-finite return")
        return _ScenarioResult(normalized_return, completed_trades)
    finally:
        hbt.close()


def probe_hftbacktest_engine() -> HftEngineProbeResult:
    import numpy as np
    from hftbacktest import (
        BacktestAsset,
        BUY_EVENT,
        DEPTH_EVENT,
        EXCH_EVENT,
        HashMapMarketDepthBacktest,
        LOCAL_EVENT,
        SELL_EVENT,
    )
    from hftbacktest.binding import event_dtype

    events = np.zeros(4, dtype=event_dtype)
    rows = (
        (DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT, 1_000_000, 100.0, 1.0),
        (DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT, 2_000_000, 100.2, 1.0),
        (DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT, 3_000_000, 100.0, 2.0),
        (DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT, 4_000_000, 100.2, 2.0),
    )
    for index, (event_flag, timestamp, price, quantity) in enumerate(rows):
        events[index]["ev"] = event_flag
        events[index]["exch_ts"] = timestamp
        events[index]["local_ts"] = timestamp
        events[index]["px"] = price
        events[index]["qty"] = quantity

    asset = (
        BacktestAsset()
        .data(events)
        .linear_asset(1.0)
        .risk_adverse_queue_model()
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0)
        .tick_size(0.1)
        .lot_size(0.001)
    )
    hbt = HashMapMarketDepthBacktest([asset])
    try:
        hbt.elapse(10_000_000)
        depth = hbt.depth(0)
        best_bid = float(depth.best_bid)
        best_ask = float(depth.best_ask)
        processed = isfinite(best_bid) and isfinite(best_ask) and best_bid <= best_ask
        return HftEngineProbeResult(
            engine="hftbacktest",
            engine_version=version("hftbacktest"),
            event_count=len(events),
            best_bid=best_bid,
            best_ask=best_ask,
            processed=processed,
        )
    finally:
        hbt.close()


def run_hftbacktest_stress_suite(
    candidate: StrategyGenome,
    *,
    dataset_hash: str,
    code_hash: str,
    cycles: int = 30,
) -> HftStressReport:
    _validate_stress_request(dataset_hash, code_hash, cycles)

    baseline = _run_hft_scenario(
        cycles=cycles,
        ask_price=100.2,
        queue_model="power_prob_queue_model",
    )
    queue_stress = _run_hft_scenario(
        cycles=cycles,
        ask_price=100.2,
        queue_model="risk_adverse_queue_model",
    )
    feed_latency = _run_hft_scenario(
        cycles=cycles,
        ask_price=100.2,
        queue_model="risk_adverse_queue_model",
        feed_latency_ns=500_000,
    )
    order_latency = _run_hft_scenario(
        cycles=cycles,
        ask_price=100.2,
        queue_model="risk_adverse_queue_model",
        order_latency_ns=500_000,
    )
    spread_stress = _run_hft_scenario(
        cycles=cycles,
        ask_price=100.1,
        queue_model="risk_adverse_queue_model",
    )

    completed_trades = min(
        baseline.completed_trades,
        queue_stress.completed_trades,
        feed_latency.completed_trades,
        order_latency.completed_trades,
        spread_stress.completed_trades,
    )
    return HftStressReport(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        engine_version=version("hftbacktest"),
        queue_model="risk_adverse_queue_model",
        baseline_return=baseline.normalized_return,
        queue_model_return=queue_stress.normalized_return,
        feed_latency_stress_return=feed_latency.normalized_return,
        order_latency_stress_return=order_latency.normalized_return,
        spread_stress_return=spread_stress.normalized_return,
        completed_trades=completed_trades,
    )
