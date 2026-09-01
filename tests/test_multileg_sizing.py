from __future__ import annotations

from decimal import Decimal

from mastertrd.nautilus_multileg_strategy import calculate_leg_order_delta


def test_weighted_leg_delta_uses_hedge_weight_and_instrument_precision() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()

    increase = calculate_leg_order_delta(
        instrument,
        base_trade_size=Decimal("0.10"),
        leg_weight=1.25,
        current_signed_quantity=Decimal("0.10000"),
    )
    reduce = calculate_leg_order_delta(
        instrument,
        base_trade_size=Decimal("0.10"),
        leg_weight=1.25,
        current_signed_quantity=Decimal("0.15000"),
    )

    assert increase == Decimal("0.02500")
    assert reduce == Decimal("-0.02500")


def test_weighted_leg_delta_preserves_short_sign_and_reversal_delta() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.btcusdt_binance()

    deepen_short = calculate_leg_order_delta(
        instrument,
        base_trade_size=Decimal("0.10"),
        leg_weight=-1.25,
        current_signed_quantity=Decimal("-0.100000"),
    )
    reverse_long = calculate_leg_order_delta(
        instrument,
        base_trade_size=Decimal("0.10"),
        leg_weight=1.25,
        current_signed_quantity=Decimal("-0.100000"),
    )

    assert deepen_short == Decimal("-0.025000")
    assert reverse_long == Decimal("0.225000")
