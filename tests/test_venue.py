import pytest

from mastertrd.venue import require_capability


def test_binance_spot_and_perpetuals_are_supported():
    require_capability("BINANCE", "spot")
    require_capability("BINANCE", "perpetuals")


def test_binance_margin_management_is_not_claimed():
    with pytest.raises(RuntimeError, match="does not provide"):
        require_capability("BINANCE", "margin")
