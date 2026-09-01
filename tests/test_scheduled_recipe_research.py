from __future__ import annotations

from types import SimpleNamespace

import mastertrd.research_candidate_generation as candidate_generation
from mastertrd.research_brain import ResearchBrainConfig
from mastertrd.research_job import default_research_job_plan
from mastertrd.strategy_universe import AssetClass, RecipeReadiness, strategy_recipe


def _config(*, recipe_ids: tuple[str, ...]) -> ResearchBrainConfig:
    return ResearchBrainConfig(
        families=("trend",),
        instruments=("BTCUSDT.BINANCE",),
        seed_start=7,
        seed_stop=9,
        screening_min_return=-1.0,
        optimization_trials=1,
        evolution_generations=1,
        evolution_population=2,
        validation_budget=1,
        paper_queue_cap=0,
        validation_window=50,
        recipe_ids=recipe_ids,
    )


def test_research_candidate_generation_honors_named_recipe_ids(monkeypatch) -> None:
    config = _config(recipe_ids=("ema-cross-crypto",))
    dataset = SimpleNamespace(
        nautilus_instruments={"BTCUSDT.BINANCE": object()},
        available_data_levels={"BTCUSDT.BINANCE": frozenset({"BAR"})},
    )
    monkeypatch.setattr(
        candidate_generation,
        "family_instrument_sets",
        lambda family, metadata, *, available_data_levels: (("BTCUSDT.BINANCE",),),
    )

    batch = candidate_generation.generate_research_candidates(config, dataset)

    assert len(batch.candidates) == 2
    assert {candidate.style for candidate in batch.candidates} == {"recipe:ema-cross-crypto"}
    assert {candidate.family for candidate in batch.candidates} == {"trend"}


def test_default_scheduled_plan_walks_executable_crypto_recipes() -> None:
    plan = default_research_job_plan()

    assert plan.runnable_recipe_ids
    assert len(plan.runnable_recipe_ids) == len(set(plan.runnable_recipe_ids))
    for recipe_id in plan.runnable_recipe_ids:
        recipe = strategy_recipe(recipe_id)
        assert recipe.readiness is RecipeReadiness.EXECUTABLE
        assert AssetClass.CRYPTO in recipe.asset_classes
        assert recipe.family in plan.runnable_families
