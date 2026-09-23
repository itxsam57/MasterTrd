import pytest

from mastertrd.venue import (
    BinanceProduct,
    binance_exchange_symbol,
    binance_product_for_instrument_id,
    infer_binance_product,
    require_capability,
)


def test_binance_spot_and_perpetuals_are_supported():
    require_capability("BINANCE", "spot")
    require_capability("BINANCE", "perpetuals")


def test_binance_margin_management_is_not_claimed():
    with pytest.raises(RuntimeError, match="does not provide"):
        require_capability("BINANCE", "margin")


def test_binance_public_instrument_identity_infers_product_and_exchange_symbol():
    assert binance_product_for_instrument_id("BTCUSDT.BINANCE") is BinanceProduct.SPOT
    assert binance_product_for_instrument_id("BTCUSDT-PERP.BINANCE") is BinanceProduct.USD_M
    assert binance_exchange_symbol("BTCUSDT.BINANCE") == "BTCUSDT"
    assert binance_exchange_symbol("BTCUSDT-PERP.BINANCE") == "BTCUSDT"
    assert infer_binance_product(("BTCUSDT.BINANCE", "ETHUSDT.BINANCE")) is BinanceProduct.SPOT
    assert infer_binance_product(
        ("BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE")
    ) is BinanceProduct.USD_M


def test_binance_public_instrument_identity_rejects_mixed_products():
    with pytest.raises(ValueError, match="mixes incompatible products"):
        infer_binance_product(("BTCUSDT.BINANCE", "ETHUSDT-PERP.BINANCE"))
