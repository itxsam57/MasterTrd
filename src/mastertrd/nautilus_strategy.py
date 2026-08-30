from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from .genome import StrategyGenome
from .strategy_families import family_spec


_TIMEFRAME_COMPONENTS = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}

_MULTI_LEG_FAMILIES = {"stat_arb", "funding_basis", "delta_neutral", "portfolio"}


class SpecialistPathRequired(ValueError):
    pass


def _trade_size(genome: StrategyGenome, override: str | None) -> Decimal:
    raw = override if override is not None else genome.entry.get("trade_size")
    try:
        if raw is None:
            raise ValueError("trade_size is required")
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("trade_size must be a positive decimal") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("trade_size must be a positive decimal")
    return value


def _timeframe_component(timeframe: str) -> str:
    try:
        return _TIMEFRAME_COMPONENTS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported Nautilus timeframe: {timeframe}") from exc


def _bar_type(instrument_id: str, timeframe: str):
    from nautilus_trader.model.data import BarType

    return BarType.from_str(
        f"{instrument_id}-{_timeframe_component(timeframe)}-LAST-EXTERNAL"
    )


def _compile_ema_baseline(genome: StrategyGenome, *, instrument, trade_size: Decimal):
    entry_kind = genome.entry.get("kind", genome.entry.get("type"))
    exit_kind = genome.exit.get("kind", genome.exit.get("type"))
    if entry_kind != "ema_cross" or exit_kind != "cross_reverse":
        raise ValueError("trend baseline requires ema_cross + cross_reverse")
    try:
        fast_period = int(genome.entry.get("fast_period", genome.entry.get("fast")))
        slow_period = int(genome.entry.get("slow_period", genome.entry.get("slow")))
    except (TypeError, ValueError) as exc:
        raise ValueError("EMA periods must be positive integers") from exc
    if fast_period <= 0 or slow_period <= 0:
        raise ValueError("EMA periods must be positive integers")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    from nautilus_trader.examples.strategies.ema_cross import EMACross, EMACrossConfig

    config = EMACrossConfig(
        instrument_id=instrument.id,
        bar_type=_bar_type(instrument.id.value, genome.timeframe),
        trade_size=trade_size,
        fast_ema_period=fast_period,
        slow_ema_period=slow_period,
        subscribe_quote_ticks=False,
        subscribe_trade_ticks=False,
        request_bars=False,
    )
    return EMACross(config=config)


def compile_genome_to_nautilus(
    genome: StrategyGenome,
    *,
    instrument,
    trade_size_override: str | None = None,
    instrument_map: Mapping[str, object] | None = None,
):
    if instrument is None:
        raise ValueError("instrument is required")

    spec = family_spec(genome.family)
    if spec.requires_hft_validation:
        raise SpecialistPathRequired(f"{genome.family} requires the specialist HFT path")

    trade_size = _trade_size(genome, trade_size_override)

    if genome.family == "trend":
        if tuple(genome.instruments) != (instrument.id.value,):
            raise ValueError("genome instrument must exactly match the Nautilus instrument")
        return _compile_ema_baseline(genome, instrument=instrument, trade_size=trade_size)

    if genome.family in _MULTI_LEG_FAMILIES:
        if len(genome.instruments) < 2:
            raise ValueError(f"{genome.family} requires at least two instruments")
        if instrument_map is None:
            raise ValueError("multi-leg compilation requires instrument_map")
        missing = [key for key in genome.instruments if key not in instrument_map]
        if missing:
            raise ValueError(f"instrument_map missing: {', '.join(missing)}")

        from .nautilus_multileg_strategy import (
            GeneratedMultiLegStrategy,
            GeneratedMultiLegStrategyConfig,
        )

        ids = tuple(instrument_map[key].id for key in genome.instruments)
        config = GeneratedMultiLegStrategyConfig(
            instrument_ids=ids,
            bar_types=tuple(_bar_type(key, genome.timeframe) for key in genome.instruments),
            trade_size=trade_size,
            family=genome.family,
            genome_hash=genome.genome_hash,
        )
        return GeneratedMultiLegStrategy(config=config, genome=genome)

    if tuple(genome.instruments) != (instrument.id.value,):
        raise ValueError("genome instrument must exactly match the Nautilus instrument")

    if genome.family == "options":
        if genome.filters.get("defined_risk_only") is not True:
            raise ValueError("options compilation requires defined_risk_only")
        from .nautilus_options_strategy import GeneratedOptionsStrategy, GeneratedOptionsStrategyConfig

        config = GeneratedOptionsStrategyConfig(
            instrument_id=instrument.id,
            bar_type=_bar_type(instrument.id.value, genome.timeframe),
            trade_size=trade_size,
            family=genome.family,
            genome_hash=genome.genome_hash,
            defined_risk_only=True,
        )
        return GeneratedOptionsStrategy(config=config, genome=genome)

    from .nautilus_bar_strategy import GeneratedBarStrategy, GeneratedBarStrategyConfig

    config = GeneratedBarStrategyConfig(
        instrument_id=instrument.id,
        bar_type=_bar_type(instrument.id.value, genome.timeframe),
        trade_size=trade_size,
        family=genome.family,
        genome_hash=genome.genome_hash,
    )
    return GeneratedBarStrategy(config=config, genome=genome)
