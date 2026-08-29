from __future__ import annotations

from dataclasses import dataclass

from .contracts import RuntimeMode
from .runtime import RuntimeConfig
from .venue import BinanceProduct


@dataclass(frozen=True, slots=True)
class BinanceExecutionProfile:
    product: BinanceProduct
    environment: str
    api_key: str
    api_secret: str


def build_binance_execution_profile(
    *,
    runtime: RuntimeConfig,
    product: BinanceProduct,
    api_key: str,
    api_secret: str,
) -> BinanceExecutionProfile:
    if not api_key or not api_secret:
        raise ValueError("API key and secret are required")
    if runtime.mode is RuntimeMode.PAPER:
        raise RuntimeError("PAPER mode does not connect to an exchange execution environment")
    environment_by_mode = {
        RuntimeMode.DEMO: "DEMO",
        RuntimeMode.TESTNET: "TESTNET",
        RuntimeMode.LIVE: "LIVE",
    }
    try:
        environment = environment_by_mode[runtime.mode]
    except KeyError as exc:
        raise RuntimeError(f"{runtime.mode} mode is not an exchange execution mode") from exc
    return BinanceExecutionProfile(
        product=product,
        environment=environment,
        api_key=api_key,
        api_secret=api_secret,
    )
