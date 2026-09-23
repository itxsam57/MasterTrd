from __future__ import annotations

import json

from mastertrd.market_universe import (
    discover_binance_liquid_universe,
    load_or_refresh_universe,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _opener_factory(*, futures: bool = False):
    symbols = [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": True,
            "contractType": "PERPETUAL",
        },
        {
            "symbol": "ETHUSDT",
            "status": "TRADING",
            "baseAsset": "ETH",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": True,
            "contractType": "PERPETUAL",
        },
        {
            "symbol": "USDCUSDT",
            "status": "TRADING",
            "baseAsset": "USDC",
            "quoteAsset": "USDT",
            "isSpotTradingAllowed": True,
            "contractType": "PERPETUAL",
        },
    ]
    tickers = [
        {"symbol": "ETHUSDT", "quoteVolume": "2000"},
        {"symbol": "BTCUSDT", "quoteVolume": "5000"},
        {"symbol": "USDCUSDT", "quoteVolume": "9000"},
    ]

    def opener(url, timeout=20):
        if "exchangeInfo" in url:
            return Response({"symbols": symbols})
        return Response(tickers)

    return opener


def test_spot_universe_ranks_liquid_markets_and_excludes_stable_base():
    rows = discover_binance_liquid_universe(
        product="SPOT",
        limit=2,
        opener=_opener_factory(),
    )
    assert [row.instrument_id for row in rows] == [
        "BTCUSDT.BINANCE",
        "ETHUSDT.BINANCE",
    ]


def test_usdm_universe_uses_nautilus_perpetual_identity():
    rows = discover_binance_liquid_universe(
        product="USD_M",
        limit=2,
        opener=_opener_factory(futures=True),
    )
    assert [row.instrument_id for row in rows] == [
        "BTCUSDT-PERP.BINANCE",
        "ETHUSDT-PERP.BINANCE",
    ]


def test_universe_cache_avoids_refetch(tmp_path):
    calls = {"count": 0}
    base = _opener_factory()

    def opener(url, timeout=20):
        calls["count"] += 1
        return base(url, timeout=timeout)

    path = tmp_path / "spot.json"
    first = load_or_refresh_universe(
        path,
        product="SPOT",
        limit=2,
        now=1000.0,
        opener=opener,
    )
    second = load_or_refresh_universe(
        path,
        product="SPOT",
        limit=2,
        now=1100.0,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache miss")),
    )
    assert first == second
    assert calls["count"] == 2
