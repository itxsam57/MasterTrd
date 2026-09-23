from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import isfinite
from pathlib import Path
import time
from typing import Callable
from urllib.request import urlopen


@dataclass(frozen=True, slots=True)
class MarketCandidate:
    product: str
    symbol: str
    instrument_id: str
    base_asset: str
    quote_asset: str
    quote_volume_24h: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_ENDPOINTS = {
    "SPOT": (
        "https://data-api.binance.vision/api/v3/exchangeInfo",
        "https://data-api.binance.vision/api/v3/ticker/24hr",
    ),
    "USD_M": (
        "https://fapi.binance.com/fapi/v1/exchangeInfo",
        "https://fapi.binance.com/fapi/v1/ticker/24hr",
    ),
}

_EXCLUDED_BASES = frozenset(
    {
        "USDT",
        "USDC",
        "FDUSD",
        "TUSD",
        "USDP",
        "USD1",
        "USDE",
        "USDS",
        "USDX",
        "RLUSD",
        "PYUSD",
        "DAI",
        "BUSD",
        "EUR",
        "TRY",
        "BRL",
    }
)


def _json_request(url: str, *, opener: Callable | None = None) -> object:
    request = urlopen if opener is None else opener
    try:
        with request(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Binance public universe request failed: {url}") from exc
    return payload


def _eligible_symbol(row: dict[str, object], *, product: str, quote_asset: str) -> bool:
    if row.get("status") != "TRADING":
        return False
    if str(row.get("quoteAsset", "")).upper() != quote_asset:
        return False
    base = str(row.get("baseAsset", "")).upper()
    if not base or base in _EXCLUDED_BASES:
        return False
    if base.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return False
    if product == "SPOT":
        return bool(row.get("isSpotTradingAllowed", True))
    return row.get("contractType") == "PERPETUAL"


def discover_binance_liquid_universe(
    *,
    product: str = "SPOT",
    quote_asset: str = "USDT",
    limit: int = 8,
    min_quote_volume: float = 0.0,
    opener: Callable | None = None,
) -> tuple[MarketCandidate, ...]:
    normalized_product = str(product).strip().upper()
    normalized_quote = str(quote_asset).strip().upper()
    if normalized_product not in _ENDPOINTS:
        raise ValueError("universe discovery currently supports SPOT and USD_M")
    if not normalized_quote:
        raise ValueError("quote_asset is required")
    if limit < 2:
        raise ValueError("universe limit must be at least two")
    if not isfinite(float(min_quote_volume)) or float(min_quote_volume) < 0.0:
        raise ValueError("min_quote_volume must be finite and non-negative")

    exchange_url, ticker_url = _ENDPOINTS[normalized_product]
    exchange_payload = _json_request(exchange_url, opener=opener)
    ticker_payload = _json_request(ticker_url, opener=opener)
    if not isinstance(exchange_payload, dict) or not isinstance(exchange_payload.get("symbols"), list):
        raise RuntimeError("Binance exchange-info universe response is invalid")
    if not isinstance(ticker_payload, list):
        raise RuntimeError("Binance 24h ticker universe response is invalid")

    metadata = {
        str(row.get("symbol", "")).upper(): row
        for row in exchange_payload["symbols"]
        if isinstance(row, dict)
        and _eligible_symbol(row, product=normalized_product, quote_asset=normalized_quote)
    }
    volume_by_symbol: dict[str, float] = {}
    for row in ticker_payload:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol", "")).upper()
        if symbol not in metadata:
            continue
        try:
            volume = float(row.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            continue
        if not isfinite(volume) or volume < float(min_quote_volume):
            continue
        volume_by_symbol[symbol] = volume

    ranked = sorted(
        volume_by_symbol,
        key=lambda symbol: (-volume_by_symbol[symbol], symbol),
    )[:limit]
    candidates: list[MarketCandidate] = []
    for symbol in ranked:
        row = metadata[symbol]
        instrument_id = (
            f"{symbol}.BINANCE"
            if normalized_product == "SPOT"
            else f"{symbol}-PERP.BINANCE"
        )
        candidates.append(
            MarketCandidate(
                product=normalized_product,
                symbol=symbol,
                instrument_id=instrument_id,
                base_asset=str(row["baseAsset"]).upper(),
                quote_asset=normalized_quote,
                quote_volume_24h=volume_by_symbol[symbol],
            )
        )
    if len(candidates) < 2:
        raise RuntimeError("Binance liquid-universe discovery returned fewer than two eligible markets")
    return tuple(candidates)


def load_or_refresh_universe(
    path: str | Path,
    *,
    product: str = "SPOT",
    quote_asset: str = "USDT",
    limit: int = 8,
    max_age_seconds: float = 3600.0,
    now: float | None = None,
    opener: Callable | None = None,
) -> tuple[MarketCandidate, ...]:
    cache_path = Path(path)
    current = time.time() if now is None else float(now)
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            age = current - float(payload["generated_at"])
            if (
                0.0 <= age <= max_age_seconds
                and payload.get("product") == str(product).strip().upper()
                and payload.get("quote_asset") == str(quote_asset).strip().upper()
                and int(payload.get("limit", 0)) == int(limit)
            ):
                rows = payload.get("markets")
                if isinstance(rows, list) and len(rows) >= 2:
                    return tuple(MarketCandidate(**dict(row)) for row in rows)
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            pass

    markets = discover_binance_liquid_universe(
        product=product,
        quote_asset=quote_asset,
        limit=limit,
        opener=opener,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": current,
        "product": str(product).strip().upper(),
        "quote_asset": str(quote_asset).strip().upper(),
        "limit": int(limit),
        "markets": [market.to_dict() for market in markets],
    }
    temporary = cache_path.with_name(f".{cache_path.name}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(cache_path)
    return markets
