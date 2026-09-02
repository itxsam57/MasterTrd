from __future__ import annotations

from mastertrd.data.orderbook import (
    OrderBookDataset,
    OrderBookEvent,
    OrderBookLevel,
    OrderBookTrade,
)
from mastertrd.genome import StrategyGenome
from mastertrd.hft_validation import HftLatencyProfile
from mastertrd.micro_profit_2s import run_micro_profit_hftbacktest


SECOND_NS = 1_000_000_000


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="MICRO-PROFIT-2S-1",
        family="market_making",
        style="micro-profit-2s",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="tick",
        entry={
            "type": "micro_profit_2s",
            "levels": 1,
            "imbalance_threshold": 0.0,
            "target_net_usd": 0.01,
            "maker_fee_bps": 1.0,
            "slippage_bps": 0.5,
            "max_quote_notional_usd": 100.0,
            "inventory_skew_bps": 1.0,
        },
        exit={"type": "micro_profit_timeout", "timeout_ms": 2000, "max_inventory": 0.10},
        filters={"spread_max_bps": 25.0},
        allow_short=True,
        data_requirements=("L2",),
    )


def synthetic_fillable_l2(*, cycles: int = 4) -> OrderBookDataset:
    events: list[OrderBookEvent] = []
    sequence = 1_000
    start = SECOND_NS
    for cycle in range(cycles):
        base = start + cycle * 2 * SECOND_NS
        rows = (
            (100_000_000, (), 30.0, 10.0),
            # Risk-adverse queue semantics require the historical aggressive trade
            # to consume the resting quantity ahead of our newly submitted quote
            # before our order can fill. Keep this fixture deliberately larger
            # than the displayed best-bid queue so it is genuinely fillable.
            (500_000_000, (OrderBookTrade("SELL", 100.0, 40.0),), 20.0, 10.0),
            (1_000_000_000, (OrderBookTrade("BUY", 100.2, 20.0),), 20.0, 20.0),
            (1_900_000_000, (), 30.0, 10.0),
        )
        for offset, trades, bid_size, ask_size in rows:
            timestamp = base + offset
            events.append(
                OrderBookEvent(
                    sequence=sequence,
                    exchange_timestamp_ns=timestamp,
                    local_timestamp_ns=timestamp + 100_000,
                    bids=(OrderBookLevel(100.0, bid_size), OrderBookLevel(99.9, 40.0)),
                    asks=(OrderBookLevel(100.2, ask_size), OrderBookLevel(100.3, 40.0)),
                    trades=trades,
                )
            )
            sequence += 1
    final_ts = start + cycles * 2 * SECOND_NS + 100_000_000
    events.append(
        OrderBookEvent(
            sequence=sequence,
            exchange_timestamp_ns=final_ts,
            local_timestamp_ns=final_ts + 100_000,
            bids=(OrderBookLevel(100.0, 30.0), OrderBookLevel(99.9, 40.0)),
            asks=(OrderBookLevel(100.2, 10.0), OrderBookLevel(100.3, 40.0)),
        )
    )
    return OrderBookDataset(
        venue="BINANCE",
        instrument="BTCUSDT",
        source_id="fixture:micro-profit-2s-fillable",
        events=tuple(events),
        synthetic=True,
    )


def test_real_hftbacktest_path_records_fee_adjusted_two_second_equity_windows() -> None:
    result = run_micro_profit_hftbacktest(
        candidate(),
        synthetic_fillable_l2(),
        latency_profile=HftLatencyProfile(feed_latency_ns=100_000, order_latency_ns=250_000),
        queue_model="risk_adverse_queue_model",
        lot_size=0.001,
        taker_fee_bps=4.0,
    )

    assert result.engine == "hftbacktest"
    assert result.dataset_hash
    assert result.completed_trades > 0
    assert result.accumulated_fee_usd > 0.0
    assert result.report.window_count >= 3
    assert result.report.window_seconds == 2.0
    assert result.report.supporting_only is True
    assert result.report.target_proven is False
    assert all(
        right - left == 2 * SECOND_NS
        for (left, _), (right, _) in zip(
            result.equity_samples,
            result.equity_samples[1:],
            strict=False,
        )
    )


def test_fee_and_slippage_stress_can_fail_the_strict_every_window_target() -> None:
    stressed = run_micro_profit_hftbacktest(
        candidate(),
        synthetic_fillable_l2(),
        latency_profile=HftLatencyProfile(feed_latency_ns=500_000, order_latency_ns=1_000_000),
        queue_model="risk_adverse_queue_model",
        lot_size=0.001,
        taker_fee_bps=10.0,
        extra_slippage_bps=20.0,
    )

    assert stressed.report.every_window_passed is False
    assert stressed.report.hit_rate < 1.0
    assert stressed.report.target_proven is False
