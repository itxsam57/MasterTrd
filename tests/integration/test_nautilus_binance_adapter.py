import threading

from mastertrd.execution import BinanceExecutionProfile
from mastertrd.nautilus_binance import (
    NautilusLiveExecutionRuntime,
    build_nautilus_binance_configs,
    build_nautilus_binance_node_config,
    build_nautilus_binance_trading_node,
)
from mastertrd.venue import BinanceProduct


def test_demo_usdm_profile_maps_to_stable_nautilus_binance_configs():
    from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment

    profile = BinanceExecutionProfile(
        product=BinanceProduct.USD_M,
        environment="DEMO",
        api_key="demo-key",
        api_secret="demo-secret",
    )
    configs = build_nautilus_binance_configs(profile=profile, account_id="BINANCE-001")

    assert configs.data.account_type is BinanceAccountType.USDT_FUTURES
    assert configs.execution.account_type is BinanceAccountType.USDT_FUTURES
    assert configs.data.environment is BinanceEnvironment.DEMO
    assert configs.execution.environment is BinanceEnvironment.DEMO
    assert configs.account_id == "BINANCE-001"


def test_spot_testnet_profile_maps_without_enabling_margin_or_options():
    from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment
    from nautilus_trader.model.identifiers import InstrumentId

    instrument_id = InstrumentId.from_str("BTCUSDT.BINANCE")
    profile = BinanceExecutionProfile(
        product=BinanceProduct.SPOT,
        environment="TESTNET",
        api_key="test-key",
        api_secret="test-secret",
    )
    configs = build_nautilus_binance_configs(
        profile=profile,
        account_id="BINANCE-TEST-001",
        instrument_ids=frozenset({instrument_id}),
    )

    assert configs.data.account_type is BinanceAccountType.SPOT
    assert configs.execution.account_type is BinanceAccountType.SPOT
    assert configs.data.environment is BinanceEnvironment.TESTNET
    assert configs.execution.environment is BinanceEnvironment.TESTNET
    assert configs.data.instrument_provider.load_all is False
    assert configs.execution.instrument_provider.load_all is False
    assert configs.data.instrument_provider.load_ids == frozenset({instrument_id})
    assert configs.execution.instrument_provider.load_ids == frozenset({instrument_id})
    assert configs.account_id == "BINANCE-TEST-001"


def test_shared_live_node_config_owns_binance_data_execution_and_reconciliation():
    from nautilus_trader.adapters.binance import BINANCE
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.model.identifiers import InstrumentId

    instrument_id = InstrumentId.from_str("BTCUSDT.BINANCE")
    profile = BinanceExecutionProfile(
        product=BinanceProduct.SPOT,
        environment="TESTNET",
        api_key="test-key",
        api_secret="test-secret",
    )
    configs = build_nautilus_binance_configs(
        profile=profile,
        account_id="BINANCE-TEST-001",
        instrument_ids=frozenset({instrument_id}),
    )

    node_config = build_nautilus_binance_node_config(
        configs=configs,
        trader_id="MASTERTRD-TESTNET-001",
        reconciliation_instrument_ids=(instrument_id,),
        reconciliation_lookback_mins=1440,
        logging=LoggingConfig(log_level="INFO"),
    )

    assert node_config.data_clients[BINANCE] is configs.data
    assert node_config.exec_clients[BINANCE] is configs.execution
    assert node_config.exec_engine.reconciliation is True
    assert node_config.exec_engine.reconciliation_lookback_mins == 1440
    assert node_config.exec_engine.reconciliation_instrument_ids == [instrument_id]
    assert str(node_config.trader_id) == "MASTERTRD-TESTNET-001"
    assert node_config.timeout_connection == 30.0
    assert node_config.timeout_reconciliation == 10.0
    assert node_config.timeout_portfolio == 10.0
    assert node_config.timeout_disconnection == 10.0
    assert node_config.timeout_post_stop == 2.0


def test_shared_trading_node_registers_both_binance_factories_and_builds_once(monkeypatch):
    from nautilus_trader.adapters.binance import BINANCE
    from nautilus_trader.adapters.binance import BinanceLiveDataClientFactory
    from nautilus_trader.adapters.binance import BinanceLiveExecClientFactory

    calls: list[tuple[str, object]] = []
    strategy = object()

    class Trader:
        def add_strategy(self, value):
            calls.append(("strategy", value))

    class FakeNode:
        def __init__(self, *, config):
            calls.append(("config", config))
            self.trader = Trader()

        def add_data_client_factory(self, name, factory):
            calls.append((f"data:{name}", factory))

        def add_exec_client_factory(self, name, factory):
            calls.append((f"exec:{name}", factory))

        def build(self):
            calls.append(("build", None))

    monkeypatch.setattr("nautilus_trader.live.node.TradingNode", FakeNode)
    config = object()
    node = build_nautilus_binance_trading_node(config=config, strategy=strategy)

    assert isinstance(node, FakeNode)
    assert calls == [
        ("config", config),
        ("strategy", strategy),
        (f"data:{BINANCE}", BinanceLiveDataClientFactory),
        (f"exec:{BINANCE}", BinanceLiveExecClientFactory),
        ("build", None),
    ]


def test_live_execution_runtime_routes_stop_through_node_loop_and_disposes_once():
    stopped = threading.Event()
    calls: list[str] = []

    class Loop:
        def is_closed(self):
            return False

        def call_soon_threadsafe(self, callback):
            calls.append("threadsafe-stop")
            callback()

    class FakeNode:
        def __init__(self):
            self.running = False
            self.loop = Loop()

        def run(self, *, raise_exception):
            assert raise_exception is True
            calls.append("run")
            self.running = True
            assert stopped.wait(timeout=2.0), "watcher did not stop live node"
            self.running = False

        def get_event_loop(self):
            return self.loop

        def stop(self):
            calls.append("stop")
            stopped.set()

        def is_running(self):
            return self.running

        def dispose(self):
            calls.append("dispose")

    runtime = NautilusLiveExecutionRuntime(FakeNode(), stop_poll_seconds=0.001)
    runtime.run(stop_requested=lambda: True)
    runtime.close()
    runtime.close()

    assert calls == ["run", "threadsafe-stop", "stop", "dispose"]
