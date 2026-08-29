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
