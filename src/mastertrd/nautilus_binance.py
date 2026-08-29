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

    # MasterTrd deliberately targets the latest stable NautilusTrader API for
    # any path that can reach real capital. The v1.231 line exposes Binance
    # configs from config.py and environment/account enums from common.enums.
    from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
    from nautilus_trader.adapters.binance.common.enums import BinanceEnvironment
    from nautilus_trader.adapters.binance.config import BinanceDataClientConfig
    from nautilus_trader.adapters.binance.config import BinanceExecClientConfig
    from nautilus_trader.model.identifiers import AccountId

    account_type_map = {
        BinanceProduct.SPOT: BinanceAccountType.SPOT,
        BinanceProduct.USD_M: BinanceAccountType.USDT_FUTURES,
        BinanceProduct.COIN_M: BinanceAccountType.COIN_FUTURES,
    }
    environment_map = {
        "LIVE": BinanceEnvironment.LIVE,
        "TESTNET": BinanceEnvironment.TESTNET,
        "DEMO": BinanceEnvironment.DEMO,
    }
    try:
        account_type = account_type_map[profile.product]
        environment = environment_map[profile.environment]
    except KeyError as exc:
        raise ValueError("unsupported Binance product or environment") from exc

    data = BinanceDataClientConfig(
        account_type=account_type,
        environment=environment,
        api_key=profile.api_key,
        api_secret=profile.api_secret,
    )
    execution = BinanceExecClientConfig(
        account_id=AccountId.from_str(account_id),
        account_type=account_type,
        environment=environment,
        api_key=profile.api_key,
        api_secret=profile.api_secret,
    )
    return NautilusBinanceConfigs(data=data, execution=execution)
