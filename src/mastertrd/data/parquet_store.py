from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Iterable

from mastertrd.contracts import MarketBar

from .archive import DatasetManifest, dataset_hash_for_bars, sha256_file, validate_bar_sequence


def write_market_bars(path: Path, bars: Iterable[MarketBar]) -> DatasetManifest:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output = Path(path)
    verified = validate_bar_sequence(bars)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")

    table = pa.table(
        {
            "timestamp": pa.array([bar.timestamp for bar in verified], type=pa.timestamp("us", tz="UTC")),
            "venue": [bar.venue for bar in verified],
            "instrument": [bar.instrument for bar in verified],
            "timeframe": [bar.timeframe for bar in verified],
            "open": [float(bar.open) for bar in verified],
            "high": [float(bar.high) for bar in verified],
            "low": [float(bar.low) for bar in verified],
            "close": [float(bar.close) for bar in verified],
            "volume": [float(bar.volume) for bar in verified],
            "extras_json": [
                json.dumps(dict(bar.extras), sort_keys=True, separators=(",", ":"), default=str)
                for bar in verified
            ],
        }
    )
    try:
        pq.write_table(table, temporary, compression="zstd")
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    return DatasetManifest(
        source="parquet",
        venue=verified[0].venue,
        instrument=verified[0].instrument,
        timeframe=verified[0].timeframe,
        first_timestamp=verified[0].timestamp,
        last_timestamp=verified[-1].timestamp,
        row_count=len(verified),
        file_sha256=sha256_file(output),
        dataset_hash=dataset_hash_for_bars(verified),
        path=output,
    )


def read_market_bars(path: Path) -> tuple[MarketBar, ...]:
    import pyarrow.parquet as pq

    table = pq.read_table(Path(path))
    required = {
        "timestamp", "venue", "instrument", "timeframe",
        "open", "high", "low", "close", "volume", "extras_json",
    }
    missing = required.difference(table.column_names)
    if missing:
        raise ValueError(f"Parquet dataset missing columns: {sorted(missing)}")

    rows = table.to_pylist()
    bars = []
    for row in rows:
        timestamp = row["timestamp"]
        if not isinstance(timestamp, datetime):
            raise ValueError("Parquet timestamp must decode as datetime")
        bars.append(
            MarketBar(
                timestamp=timestamp,
                venue=str(row["venue"]),
                instrument=str(row["instrument"]),
                timeframe=str(row["timeframe"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                extras=json.loads(row["extras_json"] or "{}"),
            )
        )
    return validate_bar_sequence(bars)
