from __future__ import annotations

from dataclasses import asdict
import json
import time
from collections.abc import Callable

from .bar_completeness import timeframe_milliseconds
from .binance_stream import BinancePublicMarketSource


def run_public_binance_closed_bar_canary(
    *,
    symbol: str = "ETHUSDT.BINANCE",
    timeframe: str = "1m",
    clock: Callable[[], float] = time.time,
    source_factory=BinancePublicMarketSource,
) -> dict[str, object]:
    width_ms = timeframe_milliseconds(timeframe)
    observed_ms = int(float(clock()) * 1_000)
    anchor_ms = (observed_ms // width_ms) * width_ms
    target_close_ms = anchor_ms + width_ms - 1

    source = source_factory(
        (symbol,),
        timeframe=timeframe,
        first_expected_start_ms=anchor_ms,
        recovery_grace_ms=3_000,
        max_reconnect_attempts=1,
    )
    for _payload in source:
        snapshot = source.completeness_snapshot
        if snapshot is None:
            raise RuntimeError("public Binance closed-bar canary completeness is unavailable")
        last_expected = snapshot.last_expected_close_ms
        if last_expected is None or last_expected < target_close_ms:
            continue
        if (
            not snapshot.data_healthy
            or snapshot.missing_closed_bars != 0
            or snapshot.last_closed_bar_ms is None
            or snapshot.last_closed_bar_ms < target_close_ms
        ):
            detail = snapshot.last_recovery_error or "target candle is incomplete"
            raise RuntimeError(f"public Binance closed-bar canary is unhealthy: {detail}")

        result = asdict(snapshot)
        result.update(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "target_start_ms": anchor_ms,
                "target_close_ms": target_close_ms,
            }
        )
        return result

    raise RuntimeError("public Binance closed-bar canary ended before the target candle completed")


if __name__ == "__main__":
    print(json.dumps(run_public_binance_closed_bar_canary(), sort_keys=True))
