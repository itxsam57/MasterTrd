from __future__ import annotations

from decimal import Decimal

import pytest

from mastertrd.genome import StrategyGenome
from mastertrd.product_contracts import validate_product_compatibility


def _genome(family: str, instruments: tuple[str, ...], *, defined_risk: bool = False) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=f"product-{family}",
        family=family,
        style=family,
        instruments=instruments,
        timeframe="1h",
        entry={"type": "volatility_signal", "iv_rv_ratio": 1.0} if family == "options" else {"type": "cointegration_spread", "window": 20, "z_entry": 2.0},
        exit={"type": "greeks_or_time_exit", "max_days": 7} if family == "options" else {"type": "spread_mean_exit", "z_exit": 0.5},
        filters={"defined_risk_only": True} if defined_risk else {},
        allow_short=family != "options",
    )


def _option():
    from nautilus_trader.model.enums import AssetClass, OptionKind
    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.model.instruments import OptionContract
    from nautilus_trader.model.objects import Currency, Price, Quantity

    return OptionContract(
        instrument_id=InstrumentId.from_str("AAPL211217C00150000.OPRA"),
        raw_symbol=Symbol("AAPL211217C00150000"),
        asset_class=AssetClass.EQUITY,
        underlying="AAPL",
        option_kind=OptionKind.CALL,
        strike_price=Price.from_str("150.00"),
        currency=Currency.from_str("USD"),
        activation_ns=1,
        expiration_ns=2,
        price_precision=2,
        price_increment=Price.from_str("0.01"),
        multiplier=Quantity.from_int(100),
        lot_size=Quantity.from_int(1),
        margin_init=Decimal("0"),
        margin_maint=Decimal("0"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
        exchange="OPRA",
    )


def test_product_contract_rejects_missing_multileg_instrument() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    eth = TestInstrumentProvider.ethusdt_binance()
    btc = TestInstrumentProvider.btcusdt_binance()
    genome = _genome("stat_arb", (eth.id.value, btc.id.value))

    with pytest.raises(ValueError, match="missing.*BTCUSDT"):
        validate_product_compatibility(genome, {eth.id.value: eth})


def test_product_contract_rejects_spot_as_option() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    spot = TestInstrumentProvider.ethusdt_binance()
    genome = _genome("options", (spot.id.value,), defined_risk=True)

    with pytest.raises(ValueError, match="option-compatible"):
        validate_product_compatibility(genome, {spot.id.value: spot})


def test_product_contract_accepts_real_option_metadata() -> None:
    option = _option()
    genome = _genome("options", (option.id.value,), defined_risk=True)

    validate_product_compatibility(genome, {option.id.value: option})


def test_product_contract_requires_defined_risk_options_policy() -> None:
    option = _option()
    genome = _genome("options", (option.id.value,), defined_risk=False)

    with pytest.raises(ValueError, match="defined_risk_only"):
        validate_product_compatibility(genome, {option.id.value: option})
