from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from math import isfinite


@dataclass(frozen=True, slots=True)
class HftEngineProbeResult:
    engine: str
    engine_version: str
    event_count: int
    best_bid: float
    best_ask: float
    processed: bool


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
