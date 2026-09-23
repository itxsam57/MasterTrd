from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from .venue import BinanceProduct


@dataclass(frozen=True, slots=True)
class NautilusReplaySummary:
    engine: str
    instrument_id: str
    event_count: int
    iterations: int


@dataclass(frozen=True, slots=True)
class NautilusStrategyReplaySummary:
    engine: str
    instrument_id: str
    event_count: int
    iterations: int
    order_count: int
    fill_count: int


def _build_binance_engine_for_instruments(
    *,
    instruments: Sequence[object],
    starting_balances: Sequence[str],
    product: str | BinanceProduct,
):
    if not instruments:
        raise ValueError("at least one instrument is required")
    if any(instrument is None for instrument in instruments):
        raise ValueError("instruments cannot contain None")
    if not starting_balances:
        raise ValueError("at least one starting balance is required")

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money

    try:
        normalized_product = BinanceProduct(str(product).strip().upper())
    except ValueError as exc:
        raise ValueError("unsupported Binance backtest product") from exc
    if normalized_product not in {BinanceProduct.SPOT, BinanceProduct.USD_M}:
        raise ValueError("unsupported Binance backtest product")

    engine = BacktestEngine(config=BacktestEngineConfig())
    venue_kwargs = {
        "venue": Venue("BINANCE"),
        "base_currency": None,
        "starting_balances": [Money.from_str(value) for value in starting_balances],
    }
    if normalized_product is BinanceProduct.SPOT:
        venue_kwargs.update(
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
        )
    else:
        venue_kwargs.update(
            oms_type=OmsType.HEDGING,
            account_type=AccountType.MARGIN,
            default_leverage=Decimal("2"),
        )
    engine.add_venue(**venue_kwargs)
    for instrument in instruments:
        engine.add_instrument(instrument)
    return engine


def _build_binance_spot_engine_for_instruments(
    *,
    instruments: Sequence[object],
    starting_balances: Sequence[str],
):
    return _build_binance_engine_for_instruments(
        instruments=instruments,
        starting_balances=starting_balances,
        product=BinanceProduct.SPOT,
    )


def _build_binance_usdm_engine_for_instruments(
    *,
    instruments: Sequence[object],
    starting_balances: Sequence[str],
):
    return _build_binance_engine_for_instruments(
        instruments=instruments,
        starting_balances=starting_balances,
        product=BinanceProduct.USD_M,
    )


def _build_binance_spot_engine(*, instrument, starting_balances: Sequence[str]):
    if instrument is None:
        raise ValueError("instrument is required")
    return _build_binance_spot_engine_for_instruments(
        instruments=(instrument,),
        starting_balances=starting_balances,
    )


def run_binance_spot_history(
    *,
    instrument,
    data: Iterable[object],
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> NautilusReplaySummary:
    events = list(data)
    if not events:
        raise ValueError("historical data is required")

    engine = _build_binance_spot_engine(
        instrument=instrument,
        starting_balances=starting_balances,
    )
    try:
        engine.add_data(events)
        engine.run()
        return NautilusReplaySummary(
            engine="nautilus_trader",
            instrument_id=instrument.id.value,
            event_count=len(events),
            iterations=int(engine.iteration),
        )
    finally:
        engine.dispose()


def run_binance_spot_strategy_history(
    *,
    instrument,
    data: Iterable[object],
    strategy,
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> NautilusStrategyReplaySummary:
    if strategy is None:
        raise ValueError("strategy is required")
    events = list(data)
    if not events:
        raise ValueError("historical data is required")

    engine = _build_binance_spot_engine(
        instrument=instrument,
        starting_balances=starting_balances,
    )
    try:
        engine.add_data(events)
        engine.add_strategy(strategy)
        engine.run()

        from nautilus_trader.analysis.reporter import ReportProvider

        orders = engine.cache.orders()
        orders_report = ReportProvider.generate_orders_report(orders)
        fills_report = ReportProvider.generate_fills_report(orders)
        return NautilusStrategyReplaySummary(
            engine="nautilus_trader",
            instrument_id=instrument.id.value,
            event_count=len(events),
            iterations=int(engine.iteration),
            order_count=int(len(orders_report.index)),
            fill_count=int(len(fills_report.index)),
        )
    finally:
        engine.dispose()
