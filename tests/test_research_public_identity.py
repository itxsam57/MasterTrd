from __future__ import annotations

import mastertrd.research_job as research_job


def test_public_archive_parser_uses_raw_binance_symbol_not_venue_qualified_id(monkeypatch, tmp_path):
    checksum = "a" * 64
    calls: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return f"{checksum}  file.zip\n".encode()

    monkeypatch.setattr(
        research_job,
        "binance_kline_url",
        lambda **kwargs: "https://data.example/file.zip",
    )
    monkeypatch.setattr(research_job, "urlopen", lambda url, timeout: _Response())
    monkeypatch.setattr(research_job, "_download", lambda url, destination: None)

    def fake_read(path, *, expected_sha256, symbol, interval):
        calls["symbol"] = symbol
        return object()

    monkeypatch.setattr(research_job, "read_binance_archive", fake_read)

    research_job._read_verified_public_archive(
        data_dir=tmp_path,
        symbol="BTCUSDT",
        instrument_id="BTCUSDT.BINANCE",
        interval="1h",
        period="2026-06",
    )

    # MarketBar identity is source symbol + separate venue. Strategy/instrument
    # maps use the venue-qualified Nautilus ID, but the archive parser must not.
    assert calls["symbol"] == "BTCUSDT"
