from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from .genome import StrategyGenome
from .product_contracts import validate_product_compatibility
from .risk_runtime import RiskRuntime
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


def _compile_ema_baseline(
    genome: StrategyGenome,
    *,
    instrument,
    trade_size: Decimal,
    risk_runtime: RiskRuntime,
):
    entry_kind = genome.entry.get("kind", genome.entry.get("type"))
    exit_kind = genome.exit.get("kind", genome.exit.get("type"))
    if entry_kind != "ema_cross":
        raise ValueError("trend entry requires ema_cross")
    if exit_kind != "cross_reverse":
        raise ValueError("trend exit requires cross_reverse")
    try:
        fast_period = int(genome.entry.get("fast_period", genome.entry.get("fast")))
        slow_period = int(genome.entry.get("slow_period", genome.entry.get("slow")))
    except (TypeError, ValueError) as exc:
        raise ValueError("EMA periods must be positive integers") from exc
    if fast_period <= 0 or slow_period <= 0:
        raise ValueError("EMA periods must be positive integers")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    from nautilus_trader.examples.strategies.ema_cross import EMACrossConfig

    from .nautilus_risk_hook import RiskManagedEMACross

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
    return RiskManagedEMACross(
        config=config,
        genome=genome,
        risk_runtime=risk_runtime,
    )


def compile_genome_to_nautilus(
    genome: StrategyGenome,
    *,
    instrument,
    trade_size_override: str | None = None,
    trade_size: str | None = None,
    instrument_map: Mapping[str, object] | None = None,
    risk_runtime: RiskRuntime | None = None,
):
    if instrument is None:
        raise ValueError("instrument is required")
    if trade_size_override is not None and trade_size is not None:
        raise ValueError("use only one of trade_size_override or trade_size")

    spec = family_spec(genome.family)
    if spec.requires_hft_validation:
        raise SpecialistPathRequired(f"{genome.family} requires the specialist HFT path")
    if risk_runtime is None:
        raise ValueError("risk_runtime is required for Nautilus strategy compilation")

    if genome.family in _MULTI_LEG_FAMILIES:
        if instrument_map is None:
            raise ValueError("multi-leg compilation requires instrument_map")
        compatibility_instruments: Mapping[str, object] = instrument_map
    else:
        compatibility_instruments = {instrument.id.value: instrument}
    validate_product_compatibility(genome, compatibility_instruments)

    effective_trade_size = _trade_size(
        genome,
        trade_size_override if trade_size_override is not None else trade_size,
    )

    if genome.family == "trend":
        return _compile_ema_baseline(
            genome,
            instrument=instrument,
            trade_size=effective_trade_size,
            risk_runtime=risk_runtime,
        )

    if genome.family in _MULTI_LEG_FAMILIES:
        assert instrument_map is not None

        from .nautilus_multileg_strategy import (
            GeneratedMultiLegStrategy,
            GeneratedMultiLegStrategyConfig,
        )

        ids = tuple(instrument_map[key].id for key in genome.instruments)
        config = GeneratedMultiLegStrategyConfig(
            instrument_ids=ids,
            bar_types=tuple(_bar_type(key, genome.timeframe) for key in genome.instruments),
            trade_size=effective_trade_size,
            family=genome.family,
            genome_hash=genome.genome_hash,
        )
        return GeneratedMultiLegStrategy(
            config=config,
            genome=genome,
            risk_runtime=risk_runtime,
        )

    if genome.family == "options":
        from .nautilus_options_strategy import GeneratedOptionsStrategy, GeneratedOptionsStrategyConfig

        config = GeneratedOptionsStrategyConfig(
            instrument_id=instrument.id,
            bar_type=_bar_type(instrument.id.value, genome.timeframe),
            trade_size=effective_trade_size,
            family=genome.family,
            genome_hash=genome.genome_hash,
            defined_risk_only=True,
        )
        return GeneratedOptionsStrategy(
            config=config,
            genome=genome,
            risk_runtime=risk_runtime,
        )

    from .nautilus_bar_strategy import GeneratedBarStrategy, GeneratedBarStrategyConfig

    config = GeneratedBarStrategyConfig(
        instrument_id=instrument.id,
        bar_type=_bar_type(instrument.id.value, genome.timeframe),
        trade_size=effective_trade_size,
        family=genome.family,
        genome_hash=genome.genome_hash,
    )
    return GeneratedBarStrategy(
        config=config,
        genome=genome,
        risk_runtime=risk_runtime,
    )
