from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .execution import BinanceExecutionProfile
from .venue import BinanceProduct


@dataclass(frozen=True, slots=True)
class NautilusBinanceConfigs:
    data: Any
    execution: Any
    account_id: str


def build_nautilus_binance_configs(
    *,
    profile: BinanceExecutionProfile,
    account_id: str,
    instrument_ids: frozenset[Any] | None = None,
) -> NautilusBinanceConfigs:
    if not account_id:
        raise ValueError("account_id is required")

    # Paths that can reach real capital intentionally target the latest stable
    # NautilusTrader v1 API. Stable v1.231 derives the venue account identity
    # after connecting, so account_id is retained by MasterTrd as its own
    # routing/reconciliation label rather than injected into BinanceExecClientConfig.
    from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
    from nautilus_trader.adapters.binance.common.enums import BinanceEnvironment
    from nautilus_trader.adapters.binance.config import BinanceDataClientConfig
    from nautilus_trader.adapters.binance.config import BinanceExecClientConfig
    from nautilus_trader.config import InstrumentProviderConfig

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

    provider = (
        InstrumentProviderConfig(load_ids=instrument_ids)
        if instrument_ids
        else InstrumentProviderConfig()
    )
    data = BinanceDataClientConfig(
        account_type=account_type,
        environment=environment,
        api_key=profile.api_key,
        api_secret=profile.api_secret,
        instrument_provider=provider,
    )
    execution = BinanceExecClientConfig(
        account_type=account_type,
        environment=environment,
        api_key=profile.api_key,
        api_secret=profile.api_secret,
        instrument_provider=provider,
        max_retries=3,
    )
    return NautilusBinanceConfigs(
        data=data,
        execution=execution,
        account_id=account_id,
    )


def build_nautilus_binance_node_config(
    *,
    configs: NautilusBinanceConfigs,
    trader_id: str,
    reconciliation_instrument_ids: Iterable[Any] | None = None,
    reconciliation_lookback_mins: int | None = None,
    logging: Any | None = None,
):
    """Build the single live-node config used by every Binance exchange mode.

    The node, not an external MasterTrd market loop, owns both live market data
    and execution clients. Startup execution reconciliation is mandatory so a
    restart must recover venue-side order state before strategies can proceed.
    """
    if not trader_id.strip():
        raise ValueError("trader_id is required")

    from nautilus_trader.adapters.binance import BINANCE
    from nautilus_trader.config import LiveExecEngineConfig
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.config import TradingNodeConfig
    from nautilus_trader.model.identifiers import TraderId

    instruments = (
        None
        if reconciliation_instrument_ids is None
        else list(reconciliation_instrument_ids)
    )
    exec_engine = LiveExecEngineConfig(
        reconciliation=True,
        reconciliation_lookback_mins=reconciliation_lookback_mins,
        reconciliation_instrument_ids=instruments,
    )
    return TradingNodeConfig(
        trader_id=TraderId(trader_id),
        logging=logging if logging is not None else LoggingConfig(log_level="INFO"),
        exec_engine=exec_engine,
        data_clients={BINANCE: configs.data},
        exec_clients={BINANCE: configs.execution},
        timeout_connection=30.0,
        timeout_reconciliation=10.0,
        timeout_portfolio=10.0,
        timeout_disconnection=10.0,
        timeout_post_stop=2.0,
    )
