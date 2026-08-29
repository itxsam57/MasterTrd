import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.credentials import BinanceCredentials, load_binance_credentials


def test_demo_credentials_are_selected_only_from_demo_namespace():
    env = {
        "BINANCE_DEMO_API_KEY": "demo-key",
        "BINANCE_DEMO_API_SECRET": "demo-secret",
        "BINANCE_DEMO_ACCOUNT_ID": "DEMO-001",
        "BINANCE_LIVE_API_KEY": "must-not-be-read",
        "BINANCE_LIVE_API_SECRET": "must-not-be-read",
    }
    credentials = load_binance_credentials(RuntimeMode.DEMO, env)
    assert credentials == BinanceCredentials("demo-key", "demo-secret", "DEMO-001")


def test_testnet_credentials_are_selected_from_testnet_namespace():
    env = {
        "BINANCE_TESTNET_API_KEY": "test-key",
        "BINANCE_TESTNET_API_SECRET": "test-secret",
        "BINANCE_TESTNET_ACCOUNT_ID": "TEST-001",
    }
    credentials = load_binance_credentials(RuntimeMode.TESTNET, env)
    assert credentials.account_id == "TEST-001"


def test_live_credentials_are_selected_from_live_namespace():
    env = {
        "BINANCE_LIVE_API_KEY": "live-key",
        "BINANCE_LIVE_API_SECRET": "live-secret",
        "BINANCE_LIVE_ACCOUNT_ID": "LIVE-001",
    }
    credentials = load_binance_credentials(RuntimeMode.LIVE, env)
    assert credentials.api_key == "live-key"


def test_paper_mode_never_loads_exchange_credentials_even_if_live_values_exist():
    env = {
        "BINANCE_LIVE_API_KEY": "live-key",
        "BINANCE_LIVE_API_SECRET": "live-secret",
        "BINANCE_LIVE_ACCOUNT_ID": "LIVE-001",
    }
    assert load_binance_credentials(RuntimeMode.PAPER, env) is None


def test_non_exchange_research_mode_never_loads_credentials():
    assert load_binance_credentials(RuntimeMode.RESEARCH, {}) is None


def test_missing_exchange_credential_fails_closed():
    with pytest.raises(ValueError, match="Missing Binance TESTNET credentials"):
        load_binance_credentials(
            RuntimeMode.TESTNET,
            {"BINANCE_TESTNET_API_KEY": "only-key"},
        )


def test_credentials_repr_never_exposes_key_or_secret():
    credentials = BinanceCredentials("key-material", "secret-material", "ACCOUNT-001")
    rendered = repr(credentials)
    assert "key-material" not in rendered
    assert "secret-material" not in rendered
    assert "ACCOUNT-001" in rendered
