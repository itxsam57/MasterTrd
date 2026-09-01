from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
from typing import Any, Callable, Iterable

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


def build_nautilus_binance_trading_node(*, config: Any, strategy: Any | None = None):
    """Construct and build the pinned Nautilus Binance live node exactly once."""
    from nautilus_trader.adapters.binance import BINANCE
    from nautilus_trader.adapters.binance import BinanceLiveDataClientFactory
    from nautilus_trader.adapters.binance import BinanceLiveExecClientFactory
    from nautilus_trader.live.node import TradingNode

    node = TradingNode(config=config)
    if strategy is not None:
        node.trader.add_strategy(strategy)
    node.add_data_client_factory(BINANCE, BinanceLiveDataClientFactory)
    node.add_exec_client_factory(BINANCE, BinanceLiveExecClientFactory)
    node.build()
    return node


class NautilusLiveExecutionRuntime:
    """Adapt a blocking Nautilus ``TradingNode`` to MasterTrd's service boundary."""

    def __init__(self, node: Any, *, stop_poll_seconds: float = 0.1) -> None:
        if stop_poll_seconds <= 0.0:
            raise ValueError("stop_poll_seconds must be positive")
        self._node = node
        self._stop_poll_seconds = float(stop_poll_seconds)
        self._closed = False

    def _request_stop(self) -> None:
        loop = self._node.get_event_loop()
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._node.stop)
        else:
            self._node.stop()

    def run(self, *, stop_requested: Callable[[], bool]) -> None:
        watcher_done = Event()

        def watch_for_stop() -> None:
            while not watcher_done.wait(self._stop_poll_seconds):
                if stop_requested():
                    self._request_stop()
                    return

        watcher = Thread(
            target=watch_for_stop,
            name="mastertrd-nautilus-stop-watchdog",
            daemon=True,
        )
        watcher.start()
        try:
            self._node.run(raise_exception=True)
        finally:
            watcher_done.set()
            watcher.join(timeout=max(1.0, self._stop_poll_seconds * 2.0))
            if self._node.is_running():
                self._request_stop()

    def close(self) -> None:
        if self._closed:
            return
        if self._node.is_running():
            self._request_stop()
        self._node.dispose()
        self._closed = True
