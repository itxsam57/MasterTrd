from mastertrd.contracts import RuntimeMode
from mastertrd.execution import BinanceExecutionProfile
from mastertrd.nautilus_binance import build_nautilus_binance_configs
from mastertrd.venue import BinanceProduct


def test_demo_usdm_profile_maps_to_nautilus_public_binance_configs():
    from nautilus_trader.adapters.binance import BinanceEnvironment, BinanceProductType

    profile = BinanceExecutionProfile(
        product=BinanceProduct.USD_M,
        environment="DEMO",
        api_key="demo-key",
        api_secret="demo-secret",
    )
    configs = build_nautilus_binance_configs(profile=profile, account_id="BINANCE-001")

    assert configs.data.product_type is BinanceProductType.USD_M
    assert configs.execution.product_type is BinanceProductType.USD_M
    assert configs.data.environment is BinanceEnvironment.DEMO
    assert configs.execution.environment is BinanceEnvironment.DEMO
    assert str(configs.execution.account_id) == "BINANCE-001"


def test_spot_testnet_profile_maps_without_enabling_margin_or_options():
    from nautilus_trader.adapters.binance import BinanceEnvironment, BinanceProductType

    profile = BinanceExecutionProfile(
        product=BinanceProduct.SPOT,
        environment="TESTNET",
        api_key="test-key",
        api_secret="test-secret",
    )
    configs = build_nautilus_binance_configs(profile=profile, account_id="BINANCE-TEST-001")

    assert configs.data.product_type is BinanceProductType.SPOT
    assert configs.execution.product_type is BinanceProductType.SPOT
    assert configs.data.environment is BinanceEnvironment.TESTNET
    assert configs.execution.environment is BinanceEnvironment.TESTNET
