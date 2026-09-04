from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import mastertrd.research_job as research_job


class _Response:
    def __init__(self, payload: bytes):
        self._buffer = BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)


def _http_error(code: int) -> HTTPError:
    return HTTPError("https://data.binance.vision/file", code, "failure", hdrs=None, fp=None)


def test_archive_download_retries_transient_503_then_atomically_succeeds(tmp_path):
    destination = tmp_path / "archive.zip"
    attempts: list[int] = []
    sleeps: list[float] = []
    outcomes = iter((_http_error(503), _http_error(503), _Response(b"verified-archive")))

    def fake_urlopen(_url: str, timeout: int):
        assert timeout == 60
        attempts.append(1)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    research_job._download(
        "https://data.binance.vision/file.zip",
        destination,
        urlopen_fn=fake_urlopen,
        sleep_fn=sleeps.append,
        max_attempts=3,
    )

    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]
    assert destination.read_bytes() == b"verified-archive"
    assert not destination.with_name(f".{destination.name}.part").exists()


def test_archive_download_does_not_retry_permanent_http_404(tmp_path):
    destination = tmp_path / "archive.zip"
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(_url: str, timeout: int):
        nonlocal attempts
        attempts += 1
        raise _http_error(404)

    with pytest.raises(HTTPError) as exc_info:
        research_job._download(
            "https://data.binance.vision/file.zip",
            destination,
            urlopen_fn=fake_urlopen,
            sleep_fn=sleeps.append,
            max_attempts=4,
        )

    assert exc_info.value.code == 404
    assert attempts == 1
    assert sleeps == []
    assert not destination.exists()
    assert not destination.with_name(f".{destination.name}.part").exists()


def test_archive_download_exhausts_transient_network_errors_without_partial_file(tmp_path):
    destination = tmp_path / "archive.zip"
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(_url: str, timeout: int):
        nonlocal attempts
        attempts += 1
        raise URLError("temporary network failure")

    with pytest.raises(URLError, match="temporary network failure"):
        research_job._download(
            "https://data.binance.vision/file.zip",
            destination,
            urlopen_fn=fake_urlopen,
            sleep_fn=sleeps.append,
            max_attempts=3,
        )

    assert attempts == 3
    assert sleeps == [1.0, 2.0]
    assert not destination.exists()
    assert not destination.with_name(f".{destination.name}.part").exists()


def test_checksum_fetch_retries_transient_error_and_returns_exact_text():
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(_url: str, timeout: int):
        nonlocal attempts
        attempts += 1
        assert timeout == 30
        if attempts == 1:
            raise _http_error(503)
        return _Response(b"a" * 64 + b"  archive.zip\n")

    text = research_job._read_url_text_with_retry(
        "https://data.binance.vision/file.zip.CHECKSUM",
        timeout=30,
        urlopen_fn=fake_urlopen,
        sleep_fn=sleeps.append,
        max_attempts=3,
    )

    assert attempts == 2
    assert sleeps == [1.0]
    assert text == ("a" * 64) + "  archive.zip\n"
