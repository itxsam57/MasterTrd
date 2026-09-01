from __future__ import annotations

import mastertrd.nautilus_paper as nautilus_paper


def test_public_binance_instrument_provider_uses_market_data_only_host(monkeypatch):
    captured: dict[str, object] = {}
    sentinel_client = object()

    def fake_http_client(**kwargs):
        captured.update(kwargs)
        return sentinel_client

    class FakeProvider:
        def __init__(self, **kwargs):
            captured["provider_client"] = kwargs["client"]
            captured["provider_account_type"] = kwargs["account_type"]
            captured["provider_environment"] = kwargs["environment"]

    monkeypatch.setattr(
        "nautilus_trader.adapters.binance.factories.get_cached_binance_http_client",
        fake_http_client,
    )
    monkeypatch.setattr(
        "nautilus_trader.adapters.binance.spot.providers.BinanceSpotInstrumentProvider",
        FakeProvider,
    )

    provider = nautilus_paper._build_public_binance_spot_provider()

    assert isinstance(provider, FakeProvider)
    assert captured["base_url"] == "https://data-api.binance.vision"
    assert captured["api_key"] is None
    assert captured["api_secret"] is None
    assert captured["provider_client"] is sentinel_client
