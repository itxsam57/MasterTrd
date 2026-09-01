from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .genome import StrategyGenome
from .research.generator import family_instrument_sets, generate_candidate
from .strategy_families import family_spec
from .strategy_universe import strategy_recipe


@dataclass(frozen=True, slots=True)
class ResearchGenerationBlocker:
    family: str
    reason: str
    required_data_level: str


@dataclass(frozen=True, slots=True)
class ResearchCandidateBatch:
    candidates: tuple[StrategyGenome, ...]
    blockers: tuple[ResearchGenerationBlocker, ...]


def generate_research_candidates(config: Any, dataset: Any) -> ResearchCandidateBatch:
    """Construct only product/data-compatible research candidates.

    Families with no compatible universe are recorded as explicit blockers rather
    than being silently downgraded or emitted as structurally invalid genomes.
    When a config supplies named recipe IDs, their exact identity is forwarded to
    the shared generator; legacy family-only callers keep the previous behavior.
    """
    missing_metadata = [
        instrument_id
        for instrument_id in config.instruments
        if instrument_id not in dataset.nautilus_instruments
    ]
    if missing_metadata:
        raise ValueError(
            "research candidate generation is missing instrument metadata for: "
            + ", ".join(missing_metadata),
        )

    metadata = {
        instrument_id: dataset.nautilus_instruments[instrument_id]
        for instrument_id in config.instruments
    }
    available_levels = {
        instrument_id: dataset.available_data_levels.get(instrument_id, frozenset())
        for instrument_id in config.instruments
    }

    candidates: list[StrategyGenome] = []
    blockers: list[ResearchGenerationBlocker] = []
    recipe_ids = tuple(getattr(config, "recipe_ids", ()))

    if recipe_ids:
        for recipe_id in recipe_ids:
            recipe = strategy_recipe(recipe_id)
            family = recipe.family
            instrument_sets = family_instrument_sets(
                family,
                metadata,
                available_data_levels=available_levels,
            )
            if not instrument_sets:
                spec = family_spec(family)
                blockers.append(
                    ResearchGenerationBlocker(
                        family=family,
                        reason="no_compatible_instrument_set",
                        required_data_level=spec.min_data_level.value,
                    ),
                )
                continue
            for instrument_set in instrument_sets:
                for seed in range(config.seed_start, config.seed_stop):
                    candidates.append(
                        generate_candidate(
                            family=family,
                            instruments=instrument_set,
                            seed=seed,
                            trade_size=config.trade_size,
                            recipe_id=recipe_id,
                        ),
                    )
        return ResearchCandidateBatch(tuple(candidates), tuple(blockers))

    for family in config.families:
        instrument_sets = family_instrument_sets(
            family,
            metadata,
            available_data_levels=available_levels,
        )
        if not instrument_sets:
            spec = family_spec(family)
            blockers.append(
                ResearchGenerationBlocker(
                    family=family,
                    reason="no_compatible_instrument_set",
                    required_data_level=spec.min_data_level.value,
                ),
            )
            continue
        for instrument_set in instrument_sets:
            for seed in range(config.seed_start, config.seed_stop):
                candidates.append(
                    generate_candidate(
                        family=family,
                        instruments=instrument_set,
                        seed=seed,
                        trade_size=config.trade_size,
                    ),
                )

    return ResearchCandidateBatch(tuple(candidates), tuple(blockers))
