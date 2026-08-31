from mastertrd.execution import BinanceExecutionProfile
from mastertrd.nautilus_binance import (
    build_nautilus_binance_configs,
    build_nautilus_binance_node_config,
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
