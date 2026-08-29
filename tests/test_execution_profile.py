import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.runtime import RuntimeConfig
from mastertrd.venue import BinanceProduct
from mastertrd.execution import BinanceExecutionProfile, build_binance_execution_profile


def test_demo_profile_uses_demo_environment_and_never_requires_live_enable():
    runtime = RuntimeConfig(mode=RuntimeMode.DEMO, live_trading_enabled=False, oracle_enabled=False)
    profile = build_binance_execution_profile(
        runtime=runtime,
        product=BinanceProduct.USD_M,
        api_key="demo-key",
        api_secret="demo-secret",
    )

    assert profile == BinanceExecutionProfile(
        product=BinanceProduct.USD_M,
        environment="DEMO",
        api_key="demo-key",
        api_secret="demo-secret",
    )


def test_live_profile_requires_explicit_live_runtime_gate():
    runtime = RuntimeConfig(mode=RuntimeMode.LIVE, live_trading_enabled=True, oracle_enabled=False)
    profile = build_binance_execution_profile(
        runtime=runtime,
        product=BinanceProduct.SPOT,
        api_key="live-key",
        api_secret="live-secret",
    )

    assert profile.environment == "LIVE"


def test_execution_profile_rejects_missing_credentials():
    runtime = RuntimeConfig(mode=RuntimeMode.TESTNET, live_trading_enabled=False, oracle_enabled=False)

    with pytest.raises(ValueError, match="API key and secret are required"):
        build_binance_execution_profile(
            runtime=runtime,
            product=BinanceProduct.SPOT,
            api_key="",
            api_secret="",
        )


def test_paper_mode_cannot_construct_exchange_execution_profile():
    runtime = RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False, oracle_enabled=False)

    with pytest.raises(RuntimeError, match="PAPER mode does not connect to an exchange execution environment"):
        build_binance_execution_profile(
            runtime=runtime,
            product=BinanceProduct.SPOT,
            api_key="x",
            api_secret="y",
        )


def test_execution_profile_repr_never_exposes_credentials():
    profile = BinanceExecutionProfile(
        product=BinanceProduct.SPOT,
        environment="TESTNET",
        api_key="visible-key-should-not-appear",
        api_secret="visible-secret-should-not-appear",
    )

    rendered = repr(profile)
    assert "visible-key-should-not-appear" not in rendered
    assert "visible-secret-should-not-appear" not in rendered
