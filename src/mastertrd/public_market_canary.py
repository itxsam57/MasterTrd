from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from .bar_completeness import timeframe_milliseconds
from .binance_stream import BinancePublicMarketSource


def _write_receipt(path: str | Path, result: dict[str, object]) -> None:
    receipt_path = Path(path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = receipt_path.with_name(f".{receipt_path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, receipt_path)


def run_public_binance_closed_bar_canary(
    *,
    symbol: str = "ETHUSDT.BINANCE",
    timeframe: str = "1m",
    required_closed_bars: int = 3,
    receipt_path: str | Path | None = None,
    clock: Callable[[], float] = time.time,
    source_factory=BinancePublicMarketSource,
) -> dict[str, object]:
    if isinstance(required_closed_bars, bool) or not isinstance(required_closed_bars, int):
        raise TypeError("required_closed_bars must be an integer")
    if required_closed_bars <= 0:
        raise ValueError("required_closed_bars must be positive")

    width_ms = timeframe_milliseconds(timeframe)
    observed_ms = int(float(clock()) * 1_000)
    anchor_ms = (observed_ms // width_ms) * width_ms
    target_close_ms = anchor_ms + (required_closed_bars * width_ms) - 1

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
            or snapshot.expected_closed_bars < required_closed_bars
            or snapshot.last_closed_bar_ms is None
            or snapshot.last_closed_bar_ms < target_close_ms
        ):
            detail = snapshot.last_recovery_error or "required consecutive candles are incomplete"
            raise RuntimeError(f"public Binance closed-bar canary is unhealthy: {detail}")

        result = asdict(snapshot)
        result.update(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "required_closed_bars": required_closed_bars,
                "target_start_ms": anchor_ms,
                "target_close_ms": target_close_ms,
            }
        )
        if receipt_path is not None:
            _write_receipt(receipt_path, result)
        return result

    raise RuntimeError("public Binance closed-bar canary ended before the target candles completed")


if __name__ == "__main__":
    receipt = os.environ.get(
        "MASTERTRD_CANARY_RECEIPT",
        "public-binance-canary-receipt.json",
    )
    print(
        json.dumps(
            run_public_binance_closed_bar_canary(receipt_path=receipt),
            sort_keys=True,
        )
    )
