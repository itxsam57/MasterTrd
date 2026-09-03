from mastertrd.binance_stream import (
    BinancePublicBookTickerSource,
    BinancePublicMarketSource,
)


def test_public_spot_market_stream_uses_binance_documented_market_data_host():
    book = BinancePublicBookTickerSource(("ETHUSDT.BINANCE",))
    market = BinancePublicMarketSource(("ETHUSDT.BINANCE",), timeframe="4h")

    assert book.uri.startswith("wss://data-stream.binance.vision/")
    assert market.uri.startswith("wss://data-stream.binance.vision/")
    assert "ethusdt@kline_4h" in market.uri
