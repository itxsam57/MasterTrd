from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
from typing import Iterable
import zipfile

from mastertrd.contracts import MarketBar

from .binance_public import parse_kline_row


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    source: str
    venue: str
    instrument: str
    timeframe: str
    first_timestamp: datetime
    last_timestamp: datetime
    row_count: int
    file_sha256: str
    dataset_hash: str
    path: Path


@dataclass(frozen=True, slots=True)
class ArchiveReadResult:
    bars: tuple[MarketBar, ...]
    manifest: DatasetManifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(path: Path, *, expected_sha256: str) -> str:
    expected = expected_sha256.strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("expected checksum must be a SHA-256 hex digest")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"checksum mismatch: expected {expected}, got {actual}")
    return actual


def _bar_identity(bar: MarketBar) -> dict[str, object]:
    return {
        "timestamp": bar.timestamp.isoformat(),
        "venue": bar.venue,
        "instrument": bar.instrument,
        "timeframe": bar.timeframe,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "extras": dict(sorted(bar.extras.items())),
    }


def dataset_hash_for_bars(bars: Iterable[MarketBar]) -> str:
    materialized = tuple(bars)
    payload = json.dumps(
        [_bar_identity(bar) for bar in materialized],
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_bar_sequence(bars: Iterable[MarketBar]) -> tuple[MarketBar, ...]:
    materialized = tuple(bars)
    if not materialized:
        raise ValueError("dataset must contain at least one market bar")
    identity = {
        (bar.venue, bar.instrument, bar.timeframe)
        for bar in materialized
    }
    if len(identity) != 1:
        venues = {bar.venue for bar in materialized}
        instruments = {bar.instrument for bar in materialized}
        timeframes = {bar.timeframe for bar in materialized}
        if len(instruments) != 1:
            raise ValueError("dataset must contain a single instrument")
        if len(venues) != 1:
            raise ValueError("dataset must contain a single venue")
        if len(timeframes) != 1:
            raise ValueError("dataset must contain a single timeframe")
    previous = None
    for bar in materialized:
        if previous is not None and bar.timestamp <= previous:
            raise ValueError("market-bar timestamps must be strictly increasing")
        previous = bar.timestamp
    return materialized


def _safe_csv_member(bundle: zipfile.ZipFile) -> zipfile.ZipInfo:
    csv_members: list[zipfile.ZipInfo] = []
    for member in bundle.infolist():
        name = member.filename.replace("\\", "/")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"unsafe archive member: {member.filename}")
        if member.is_dir():
            continue
        if pure.suffix.lower() == ".csv":
            csv_members.append(member)
    if len(csv_members) != 1:
        raise ValueError("Binance archive must contain exactly one CSV file")
    return csv_members[0]


def read_binance_archive(
    path: Path,
    *,
    expected_sha256: str,
    symbol: str,
    interval: str,
    venue: str = "BINANCE",
) -> ArchiveReadResult:
    archive_path = Path(path)
    file_sha = verify_archive(archive_path, expected_sha256=expected_sha256)
    try:
        with zipfile.ZipFile(archive_path, "r") as bundle:
            member = _safe_csv_member(bundle)
            raw = bundle.read(member)
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid ZIP archive") from exc

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("archive CSV must be UTF-8") from exc

    bars = []
    reader = csv.reader(io.StringIO(text))
    for row_number, row in enumerate(reader, start=1):
        if not row or all(not str(value).strip() for value in row):
            continue
        try:
            bars.append(
                parse_kline_row(row, symbol=symbol, interval=interval, venue=venue)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid Binance kline row {row_number}: {exc}") from exc

    verified = validate_bar_sequence(bars)
    manifest = DatasetManifest(
        source="binance-public-data",
        venue=verified[0].venue,
        instrument=verified[0].instrument,
        timeframe=verified[0].timeframe,
        first_timestamp=verified[0].timestamp,
        last_timestamp=verified[-1].timestamp,
        row_count=len(verified),
        file_sha256=file_sha,
        dataset_hash=dataset_hash_for_bars(verified),
        path=archive_path,
    )
    return ArchiveReadResult(bars=verified, manifest=manifest)
