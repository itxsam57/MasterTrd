from __future__ import annotations

from decimal import Decimal
from importlib import import_module
from importlib.util import find_spec


def test_testnet_smoke_runner_exists_and_rounds_up_to_venue_minimum():
    spec = find_spec("mastertrd.testnet_smoke")
    assert spec is not None, "missing production TESTNET smoke runner"

    module = import_module("mastertrd.testnet_smoke")
    calculate = getattr(module, "calculate_minimum_order_quantity", None)
    assert callable(calculate), "TESTNET smoke runner must expose minimum-size calculation"

    quantity = calculate(
        min_notional=Decimal("5"),
        limit_price=Decimal("49995"),
        step_size=Decimal("0.00001"),
        min_quantity=Decimal("0.00001"),
    )

    assert quantity == Decimal("0.00011")
    assert quantity * Decimal("49995") >= Decimal("5")


def test_testnet_smoke_runner_never_rounds_below_exchange_min_quantity():
    spec = find_spec("mastertrd.testnet_smoke")
    assert spec is not None, "missing production TESTNET smoke runner"

    module = import_module("mastertrd.testnet_smoke")
    calculate = getattr(module, "calculate_minimum_order_quantity", None)
    assert callable(calculate)

    quantity = calculate(
        min_notional=Decimal("1"),
        limit_price=Decimal("100000"),
        step_size=Decimal("0.0001"),
        min_quantity=Decimal("0.001"),
    )

    assert quantity == Decimal("0.001")
