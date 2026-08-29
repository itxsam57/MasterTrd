import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.runtime import RuntimeConfig


def test_default_runtime_is_safe_paper():
    cfg = RuntimeConfig.from_env({})
    assert cfg.mode is RuntimeMode.PAPER
    assert not cfg.live_trading_enabled


def test_live_fails_closed_without_explicit_enable():
    with pytest.raises(RuntimeError, match="requires"):
        RuntimeConfig.from_env({"MASTERTRD_MODE": "LIVE"})


def test_live_flag_cannot_be_enabled_in_paper():
    with pytest.raises(RuntimeError, match="outside LIVE"):
        RuntimeConfig.from_env({"MASTERTRD_MODE": "PAPER", "LIVE_TRADING_ENABLED": "true"})
