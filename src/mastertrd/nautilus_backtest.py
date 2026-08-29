from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


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


def _build_binance_spot_engine(*, instrument, starting_balances: Sequence[str]):
    if instrument is None:
        raise ValueError("instrument is required")
    if not starting_balances:
        raise ValueError("at least one starting balance is required")

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money

    engine = BacktestEngine(config=BacktestEngineConfig())
    engine.add_venue(
        venue=Venue("BINANCE"),
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money.from_str(value) for value in starting_balances],
    )
    engine.add_instrument(instrument)
    return engine


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

        orders_report = engine.generate_orders_report()
        fills_report = engine.generate_fills_report()
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
