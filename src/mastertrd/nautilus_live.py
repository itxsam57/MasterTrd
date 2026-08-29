from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .execution import BinanceExecutionProfile
from .nautilus_binance import build_nautilus_binance_configs


@dataclass(frozen=True, slots=True)
class NautilusLiveNodeBuild:
    node: Any
    trader_id: str
    account_id: str
    environment: str


def build_nautilus_binance_trading_node(
    *,
    profile: BinanceExecutionProfile,
    account_id: str,
    trader_id: str = "MASTERTRD-001",
):
    """Build, but do not start, the authoritative Nautilus Binance node.

    Network connections and order execution begin only when the caller invokes
    ``node.run()``. The profile is already mode-gated by MasterTrd before this
    function is reached. This builder deliberately contains no strategy and no
    fallback environment: strategies must be explicitly admitted by the
    Promotion Governor and attached by the controlled execution layer.
    """
    if not trader_id.strip():
        raise ValueError("trader_id is required")

    configs = build_nautilus_binance_configs(profile=profile, account_id=account_id)

    from nautilus_trader.adapters.binance import BINANCE
    from nautilus_trader.adapters.binance import BinanceLiveDataClientFactory
    from nautilus_trader.adapters.binance import BinanceLiveExecClientFactory
    from nautilus_trader.config import LiveExecEngineConfig
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.config import TradingNodeConfig
    from nautilus_trader.live.node import TradingNode
    from nautilus_trader.model.identifiers import TraderId

    config = TradingNodeConfig(
        trader_id=TraderId(trader_id),
        logging=LoggingConfig(log_level="INFO", use_pyo3=True),
        exec_engine=LiveExecEngineConfig(reconciliation=True),
        data_clients={BINANCE: configs.data},
        exec_clients={BINANCE: configs.execution},
        timeout_connection=20.0,
        timeout_reconciliation=10.0,
        timeout_portfolio=10.0,
        timeout_disconnection=10.0,
        timeout_post_stop=2.0,
    )
    node = TradingNode(config=config)
    node.add_data_client_factory(BINANCE, BinanceLiveDataClientFactory)
    node.add_exec_client_factory(BINANCE, BinanceLiveExecClientFactory)
    node.build()
    return node
