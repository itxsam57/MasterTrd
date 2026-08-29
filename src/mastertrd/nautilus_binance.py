from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .execution import BinanceExecutionProfile
from .venue import BinanceProduct


@dataclass(frozen=True, slots=True)
class NautilusBinanceConfigs:
    data: Any
    execution: Any


def build_nautilus_binance_configs(
    *,
    profile: BinanceExecutionProfile,
    account_id: str,
) -> NautilusBinanceConfigs:
    if not account_id:
        raise ValueError("account_id is required")

    from nautilus_trader.adapters.binance import BinanceDataClientConfig
    from nautilus_trader.adapters.binance import BinanceEnvironment
    from nautilus_trader.adapters.binance import BinanceExecutionClientConfig
    from nautilus_trader.adapters.binance import BinanceProductType
    from nautilus_trader.model import AccountId

    product_map = {
        BinanceProduct.SPOT: BinanceProductType.SPOT,
        BinanceProduct.USD_M: BinanceProductType.USD_M,
        BinanceProduct.COIN_M: BinanceProductType.COIN_M,
    }
    environment_map = {
        "LIVE": BinanceEnvironment.LIVE,
        "TESTNET": BinanceEnvironment.TESTNET,
        "DEMO": BinanceEnvironment.DEMO,
    }
    try:
        product_type = product_map[profile.product]
        environment = environment_map[profile.environment]
    except KeyError as exc:
        raise ValueError("unsupported Binance product or environment") from exc

    data = BinanceDataClientConfig(
        product_type=product_type,
        environment=environment,
        api_key=profile.api_key,
        api_secret=profile.api_secret,
    )
    execution = BinanceExecutionClientConfig(
        account_id=AccountId.from_str(account_id),
        product_type=product_type,
        environment=environment,
        api_key=profile.api_key,
        api_secret=profile.api_secret,
    )
    return NautilusBinanceConfigs(data=data, execution=execution)
