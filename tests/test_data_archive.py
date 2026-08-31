from __future__ import annotations

import csv
import hashlib
import io
import zipfile

import pytest

from mastertrd.data.archive import read_binance_archive, verify_archive


def _zip_bytes(filename: str, rows: list[list[object]]) -> bytes:
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerows(rows)
    payload = csv_buffer.getvalue().encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(filename, payload)
    return output.getvalue()


def test_verify_archive_rejects_checksum_mismatch(tmp_path) -> None:
    archive = tmp_path / "bars.zip"
    archive.write_bytes(b"not-a-real-archive")

    with pytest.raises(ValueError, match="checksum"):
        verify_archive(archive, expected_sha256="0" * 64)


def test_read_binance_archive_rejects_path_traversal(tmp_path) -> None:
    archive = tmp_path / "bars.zip"
    archive.write_bytes(_zip_bytes("../escape.csv", [[1, 1, 1, 1, 1, 1]]))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="unsafe archive member"):
        read_binance_archive(
            archive,
            expected_sha256=checksum,
            symbol="BTCUSDT",
            interval="1m",
        )


def test_read_binance_archive_rejects_duplicate_or_non_monotonic_timestamps(tmp_path) -> None:
    rows = [
        [1_700_000_000_000, 100, 101, 99, 100.5, 10],
        [1_700_000_000_000, 100.5, 102, 100, 101, 11],
    ]
    archive = tmp_path / "bars.zip"
    archive.write_bytes(_zip_bytes("BTCUSDT-1m.csv", rows))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="strictly increasing"):
        read_binance_archive(
            archive,
            expected_sha256=checksum,
            symbol="BTCUSDT",
            interval="1m",
        )


def test_read_binance_archive_returns_verified_bars_and_hash(tmp_path) -> None:
    rows = [
        [1_700_000_000_000, 100, 101, 99, 100.5, 10],
        [1_700_000_060_000, 100.5, 102, 100, 101, 11],
    ]
    archive = tmp_path / "bars.zip"
    archive.write_bytes(_zip_bytes("BTCUSDT-1m.csv", rows))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

    result = read_binance_archive(
        archive,
        expected_sha256=checksum,
        symbol="BTCUSDT",
        interval="1m",
    )

    assert len(result.bars) == 2
    assert result.manifest.row_count == 2
    assert result.manifest.file_sha256 == checksum
    assert len(result.manifest.dataset_hash) == 64
    assert result.manifest.instrument == "BTCUSDT"
    assert result.manifest.timeframe == "1m"
