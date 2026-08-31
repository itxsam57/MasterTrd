from mastertrd.execution import BinanceExecutionProfile
from mastertrd.nautilus_binance import build_nautilus_binance_configs
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
