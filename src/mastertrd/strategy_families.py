from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class DataLevel(StrEnum):
    BAR = "BAR"
    TICK = "TICK"
    L2 = "L2"
    L3 = "L3"


@dataclass(frozen=True, slots=True)
class StrategyFamilySpec:
    key: str
    min_data_level: DataLevel
    requires_hft_validation: bool
    supports_short: bool


FAMILIES: Mapping[str, StrategyFamilySpec] = {
    "trend": StrategyFamilySpec("trend", DataLevel.BAR, False, True),
    "momentum": StrategyFamilySpec("momentum", DataLevel.BAR, False, True),
    "breakout": StrategyFamilySpec("breakout", DataLevel.BAR, False, True),
    "mean_reversion": StrategyFamilySpec("mean_reversion", DataLevel.BAR, False, True),
    "volatility": StrategyFamilySpec("volatility", DataLevel.BAR, False, True),
    "swing": StrategyFamilySpec("swing", DataLevel.BAR, False, True),
    "position": StrategyFamilySpec("position", DataLevel.BAR, False, True),
    "stat_arb": StrategyFamilySpec("stat_arb", DataLevel.BAR, False, True),
    "funding_basis": StrategyFamilySpec("funding_basis", DataLevel.BAR, False, True),
    "delta_neutral": StrategyFamilySpec("delta_neutral", DataLevel.BAR, False, True),
    "options": StrategyFamilySpec("options", DataLevel.BAR, False, True),
    "portfolio": StrategyFamilySpec("portfolio", DataLevel.BAR, False, True),
    "scalping": StrategyFamilySpec("scalping", DataLevel.TICK, True, True),
    "grid": StrategyFamilySpec("grid", DataLevel.TICK, True, True),
    "market_making": StrategyFamilySpec("market_making", DataLevel.L2, True, True),
    "order_book": StrategyFamilySpec("order_book", DataLevel.L2, True, True),
    "cross_venue_arb": StrategyFamilySpec("cross_venue_arb", DataLevel.TICK, True, True),
}


def family_spec(key: str) -> StrategyFamilySpec:
    try:
        return FAMILIES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported strategy family: {key}") from exc
