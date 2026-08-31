from __future__ import annotations

from collections.abc import Mapping

from .genome import StrategyGenome
from .strategy_families import family_spec


def _instrument_id_value(instrument: object) -> str:
    instrument_id = getattr(instrument, "id", None)
    value = getattr(instrument_id, "value", None)
    if not isinstance(value, str) or not value:
        raise ValueError("instrument metadata requires a concrete Nautilus instrument id")
    return value


def _is_option_instrument(instrument: object) -> bool:
    from nautilus_trader.model.instruments import CryptoOption, OptionContract

    return isinstance(instrument, (OptionContract, CryptoOption))


def validate_product_compatibility(
    genome: StrategyGenome,
    instruments: Mapping[str, object],
) -> None:
    """Fail closed unless concrete Nautilus products match the genome contract exactly."""
    if not isinstance(instruments, Mapping) or not instruments:
        raise ValueError("instrument metadata mapping is required")

    spec = family_spec(genome.family)
    expected = tuple(genome.instruments)
    expected_set = set(expected)
    supplied_set = set(instruments)

    missing = [instrument_id for instrument_id in expected if instrument_id not in supplied_set]
    if missing:
        raise ValueError(f"missing instrument metadata for: {', '.join(missing)}")
    extras = sorted(supplied_set - expected_set)
    if extras:
        raise ValueError(f"unexpected instrument metadata for: {', '.join(extras)}")

    count = len(expected)
    if count < spec.min_instruments:
        raise ValueError(
            f"{genome.family} requires at least {spec.min_instruments} instrument(s)",
        )
    if spec.max_instruments is not None and count > spec.max_instruments:
        raise ValueError(
            f"{genome.family} supports at most {spec.max_instruments} instrument(s)",
        )

    concrete: list[object] = []
    for instrument_id in expected:
        instrument = instruments[instrument_id]
        actual_id = _instrument_id_value(instrument)
        if actual_id != instrument_id:
            raise ValueError(
                f"instrument metadata id mismatch: expected {instrument_id}, got {actual_id}",
            )
        concrete.append(instrument)

    if spec.requires_option_product:
        if genome.filters.get("defined_risk_only") is not True:
            raise ValueError("options compilation requires defined_risk_only")
        if not all(_is_option_instrument(instrument) for instrument in concrete):
            raise ValueError("options family requires option-compatible instrument metadata")
    elif any(_is_option_instrument(instrument) for instrument in concrete):
        raise ValueError("option instruments require the options family")
