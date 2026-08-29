from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .genome import StrategyGenome
from .strategy_families import family_spec


_TIMEFRAME_COMPONENTS = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "1h": "1-HOUR",
}


def compile_genome_to_nautilus(genome: StrategyGenome, *, instrument):
    if instrument is None:
        raise ValueError("instrument is required")

    spec = family_spec(genome.family)
    if spec.requires_hft_validation:
        raise ValueError(f"{genome.family} requires the specialist HFT path")

    instrument_id = instrument.id.value
    if tuple(genome.instruments) != (instrument_id,):
        raise ValueError("genome instrument must exactly match the Nautilus instrument")

    if genome.entry.get("kind") != "ema_cross":
        raise ValueError("unsupported Nautilus entry kind")
    if genome.exit.get("kind") != "cross_reverse":
        raise ValueError("unsupported Nautilus exit kind")

    try:
        fast_period = int(genome.entry["fast_period"])
        slow_period = int(genome.entry["slow_period"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("EMA periods must be positive integers") from exc
    if fast_period <= 0 or slow_period <= 0:
        raise ValueError("EMA periods must be positive integers")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    try:
        trade_size = Decimal(str(genome.entry["trade_size"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("trade_size must be a positive decimal") from exc
    if not trade_size.is_finite() or trade_size <= 0:
        raise ValueError("trade_size must be a positive decimal")

    try:
        timeframe_component = _TIMEFRAME_COMPONENTS[genome.timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported Nautilus timeframe: {genome.timeframe}") from exc

    from nautilus_trader.examples.strategies.ema_cross import EMACross, EMACrossConfig
    from nautilus_trader.model.data import BarType

    bar_type = BarType.from_str(
        f"{instrument_id}-{timeframe_component}-LAST-INTERNAL"
    )
    config = EMACrossConfig(
        instrument_id=instrument.id,
        bar_type=bar_type,
        trade_size=trade_size,
        fast_ema_period=fast_period,
        slow_ema_period=slow_period,
        subscribe_quote_ticks=False,
        subscribe_trade_ticks=False,
        request_bars=False,
    )
    return EMACross(config=config)
