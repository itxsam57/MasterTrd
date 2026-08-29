from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from .contracts import RuntimeMode


@dataclass(frozen=True, slots=True)
class BinanceCredentials:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    account_id: str


def load_binance_credentials(
    mode: RuntimeMode,
    environ: Mapping[str, str] | None = None,
) -> BinanceCredentials | None:
    env = os.environ if environ is None else environ
    namespace_by_mode = {
        RuntimeMode.DEMO: "DEMO",
        RuntimeMode.TESTNET: "TESTNET",
        RuntimeMode.LIVE: "LIVE",
    }
    namespace = namespace_by_mode.get(mode)
    if namespace is None:
        return None

    prefix = f"BINANCE_{namespace}"
    api_key = env.get(f"{prefix}_API_KEY", "").strip()
    api_secret = env.get(f"{prefix}_API_SECRET", "").strip()
    account_id = env.get(f"{prefix}_ACCOUNT_ID", "").strip()
    if not api_key or not api_secret or not account_id:
        raise ValueError(f"Missing Binance {namespace} credentials")

    return BinanceCredentials(
        api_key=api_key,
        api_secret=api_secret,
        account_id=account_id,
    )
