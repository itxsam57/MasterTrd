from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class NautilusReplaySummary:
    engine: str
    instrument_id: str
    event_count: int
    iterations: int


def run_binance_spot_history(
    *,
    instrument,
    data: Iterable[object],
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> NautilusReplaySummary:
    if instrument is None:
        raise ValueError("instrument is required")
    events = list(data)
    if not events:
        raise ValueError("historical data is required")
    if not starting_balances:
        raise ValueError("at least one starting balance is required")

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money

    venue = Venue("BINANCE")
    engine = BacktestEngine(config=BacktestEngineConfig())
    try:
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=None,
            starting_balances=[Money.from_str(value) for value in starting_balances],
        )
        engine.add_instrument(instrument)
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
