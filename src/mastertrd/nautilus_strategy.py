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


def compile_hft_genome_to_nautilus(
    genome: StrategyGenome,
    *,
    instruments: Mapping[str, object],
    trade_size_override: str | None = None,
    trade_size: str | None = None,
    risk_runtime: RiskRuntime | None = None,
):
    """Compile an HFT family onto its dedicated Nautilus execution boundary."""
    if trade_size_override is not None and trade_size is not None:
        raise ValueError("use only one of trade_size_override or trade_size")

    spec = family_spec(genome.family)
    if not spec.requires_hft_validation:
        raise ValueError(f"{genome.family} is not an HFT specialist family")
    if risk_runtime is None:
        raise ValueError("risk_runtime is required for HFT Nautilus strategy compilation")
    if spec.min_data_level not in {"TICK", "L2"}:
        raise ValueError(f"unsupported HFT data level: {spec.min_data_level}")
    if spec.min_data_level not in genome.data_requirements:
        raise ValueError(
            f"{genome.family} requires {spec.min_data_level} market data for execution",
        )

    validate_product_compatibility(genome, instruments)
    effective_trade_size = _trade_size(
        genome,
        trade_size_override if trade_size_override is not None else trade_size,
    )

    from .hft_strategy import GeneratedHftStrategy, GeneratedHftStrategyConfig

    config = GeneratedHftStrategyConfig(
        instrument_ids=tuple(instruments[key].id for key in genome.instruments),
        trade_size=effective_trade_size,
        family=genome.family,
        genome_hash=genome.genome_hash,
        data_level=spec.min_data_level,
    )
    return GeneratedHftStrategy(
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

    # All single-leg BAR families, including trend, use the same MasterTrd
    # signal/exit semantics in research, backtest, PAPER and promotion-grade
    # execution. The Nautilus bundled EMA example is deliberately not part of
    # this path because it is an example/test strategy rather than our alpha
    # contract.
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
