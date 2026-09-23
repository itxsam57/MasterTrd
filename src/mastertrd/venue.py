from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class BinanceProduct(StrEnum):
    SPOT = "SPOT"
    USD_M = "USD_M"
    COIN_M = "COIN_M"


@dataclass(frozen=True, slots=True)
class VenueCapabilities:
    spot: bool
    margin: bool
    perpetuals: bool
    delivery_futures: bool
    options: bool


VENUES: Mapping[str, VenueCapabilities] = {
    # Nautilus' current Binance adapter supports Spot, USD-M and COIN-M futures.
    # Binance margin account management is explicitly not implemented by that adapter.
    "BINANCE": VenueCapabilities(True, False, True, True, False),
}


def require_capability(venue: str, capability: str) -> None:
    try:
        caps = VENUES[venue]
    except KeyError as exc:
        raise ValueError(f"unsupported venue: {venue}") from exc
    if not hasattr(caps, capability):
        raise ValueError(f"unknown capability: {capability}")
    if not getattr(caps, capability):
        raise RuntimeError(f"{venue} adapter does not provide capability: {capability}")


def binance_product_for_instrument_id(instrument_id: str) -> BinanceProduct:
    normalized = str(instrument_id).strip().upper()
    if not normalized.endswith(".BINANCE"):
        raise ValueError("Binance instrument ID must use the BINANCE venue")
    symbol = normalized.rsplit(".", 1)[0]
    if not symbol:
        raise ValueError("Binance instrument symbol is required")
    if symbol.endswith("-PERP"):
        return BinanceProduct.USD_M
    if "-" in symbol:
        raise ValueError("unsupported Binance public PAPER instrument identity")
    return BinanceProduct.SPOT


def infer_binance_product(instrument_ids) -> BinanceProduct:
    values = tuple(str(value).strip().upper() for value in instrument_ids)
    if not values:
        raise ValueError("at least one Binance instrument is required")
    products = {binance_product_for_instrument_id(value) for value in values}
    if len(products) != 1:
        raise ValueError("Binance instrument set mixes incompatible products")
    return next(iter(products))


def binance_exchange_symbol(instrument_id: str) -> str:
    product = binance_product_for_instrument_id(instrument_id)
    symbol = str(instrument_id).strip().upper().rsplit(".", 1)[0]
    if product is BinanceProduct.USD_M:
        symbol = symbol.removesuffix("-PERP")
    if not symbol or not symbol.isalnum():
        raise ValueError("Binance exchange symbol must be alphanumeric")
    return symbol
