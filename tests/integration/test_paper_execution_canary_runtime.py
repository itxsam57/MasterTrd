from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mastertrd.bar_completeness import BarCompletenessSnapshot, timeframe_milliseconds
from mastertrd.contracts import MarketBar
from mastertrd.paper_execution_canary import (
    execution_canary_lanes,
    run_paper_execution_canary_lane,
    validate_execution_canary_result,
)


def _history(symbol: str, timeframe: str, *, limit: int):
    del limit
    width = timeframe_milliseconds(timeframe)
    anchor_ms = (1_800_000_000_000 // width) * width
    close_ms = anchor_ms - 1
    return [
        MarketBar(
            timestamp=datetime.fromtimestamp(close_ms / 1_000.0, tz=timezone.utc),
            venue="BINANCE",
            instrument=symbol,
            timeframe=timeframe,
            open=2000.0,
            high=2001.0,
            low=1999.0,
            close=2000.0,
            volume=10.0,
            extras={
                "source_kline_start_ms": anchor_ms - width,
                "source_kline_close_ms": close_ms,
            },
        )
    ]


class _FakeSource:
    def __init__(self, instruments, *, timeframe, first_expected_start_ms, **_kwargs):
        self.symbol = str(tuple(instruments)[0]).split(".", 1)[0]
        self.timeframe = timeframe
        self.first_expected_start_ms = int(first_expected_start_ms)
        self.completeness_snapshot = BarCompletenessSnapshot(
            expected_closed_bars=0,
            ws_closed_bars=0,
            rest_recovered_bars=0,
            missing_closed_bars=0,
            recovery_failures=0,
            last_closed_bar_ms=None,
            last_expected_close_ms=None,
            last_recovery_error=None,
            data_healthy=True,
        )

    def __iter__(self):
        width = timeframe_milliseconds(self.timeframe)
        for count in range(1, 9):
            start_ms = self.first_expected_start_ms + (count - 1) * width
            close_ms = start_ms + width - 1
            midpoint = 2000.0 + count
            yield {
                "event_id": f"tick-{self.timeframe}-{count}",
                "venue": "BINANCE",
                "instrument": self.symbol,
                "timestamp_ms": close_ms - 1_000,
                "bid": midpoint - 0.05,
                "ask": midpoint + 0.05,
                "bid_size": 5.0,
                "ask_size": 5.0,
                "last": midpoint,
                "last_size": 0.0,
                "realized_volatility": 0.01,
            }
            self.completeness_snapshot = BarCompletenessSnapshot(
                expected_closed_bars=count,
                ws_closed_bars=count,
                rest_recovered_bars=0,
                missing_closed_bars=0,
                recovery_failures=0,
                last_closed_bar_ms=close_ms,
                last_expected_close_ms=close_ms,
                last_recovery_error=None,
                data_healthy=True,
            )
            yield {
                "event_id": f"bar-{self.timeframe}-{count}",
                "venue": "BINANCE",
                "instrument": self.symbol,
                "timeframe": self.timeframe,
                "timestamp_ms": close_ms,
                "open": midpoint - 1.0,
                "high": midpoint + 1.0,
                "low": midpoint - 1.5,
                "close": midpoint,
                "volume": 10.0,
                "spread_bps": 0.5,
                "realized_volatility": 0.01,
                "source_kline_start_ms": start_ms,
                "source_kline_close_ms": close_ms,
            }


@pytest.mark.parametrize("lane", execution_canary_lanes(), ids=lambda lane: lane.name)
def test_execution_canary_lane_uses_real_nautilus_risk_and_reconciliation(lane) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    result = run_paper_execution_canary_lane(
        lane,
        instrument_loader=lambda _symbol: TestInstrumentProvider.ethusdt_binance(),
        history_loader=_history,
        source_factory=_FakeSource,
        code_hash="canary-test-code",
        deadline_seconds=30.0,
    )

    validate_execution_canary_result(lane, result)
    assert result["orders_attempted"] >= lane.minimum_orders
    assert result["orders_allowed"] >= lane.minimum_orders
    assert result["orders_rejected"] == 0
    assert result["reconciliation_errors"] == 0
    assert result["final_flat"] is True
