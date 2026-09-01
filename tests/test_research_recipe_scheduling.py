from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import mastertrd.research_candidate_generation as candidate_generation
import mastertrd.research_job as research_job
from mastertrd.research_brain import ResearchBrainConfig
from mastertrd.strategy_families import DataLevel, family_spec
from mastertrd.strategy_universe import AssetClass, RecipeReadiness, strategy_recipe


def _config(*, recipe_ids: tuple[str, ...] = ()) -> ResearchBrainConfig:
    return ResearchBrainConfig(
        families=("trend",),
        instruments=("BTCUSDT.BINANCE",),
        seed_start=5,
        seed_stop=7,
        screening_min_return=-1.0,
        optimization_trials=1,
        evolution_generations=1,
        evolution_population=2,
        validation_budget=1,
        paper_queue_cap=0,
        validation_window=50,
        recipe_ids=recipe_ids,
    )


def test_default_public_job_selects_multiple_exact_crypto_bar_recipes_per_runnable_family() -> None:
    plan = research_job.default_research_job_plan()
    assert plan.runnable_recipe_ids

    family_counts = Counter()
    for recipe_id in plan.runnable_recipe_ids:
        recipe = strategy_recipe(recipe_id)
        family_counts[recipe.family] += 1
        assert recipe.readiness is RecipeReadiness.EXECUTABLE
        assert AssetClass.CRYPTO in recipe.asset_classes
        assert recipe.family in plan.runnable_families
        assert family_spec(recipe.family).min_data_level is DataLevel.BAR

    assert all(family_counts[family] >= 2 for family in plan.runnable_families)


def test_research_brain_config_rejects_recipe_from_unconfigured_family() -> None:
    try:
        _config(recipe_ids=("rsi-momentum-balanced",))
    except ValueError as exc:
        assert "recipe family must be configured" in str(exc)
    else:
        raise AssertionError("recipe from an unconfigured family must fail closed")


def test_candidate_generation_passes_exact_recipe_identity_to_generator(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        candidate_generation,
        "family_instrument_sets",
        lambda family, metadata, *, available_data_levels: (("BTCUSDT.BINANCE",),),
    )
    monkeypatch.setattr(
        candidate_generation,
        "generate_candidate",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(family=kwargs["family"]),
    )
    dataset = SimpleNamespace(
        nautilus_instruments={"BTCUSDT.BINANCE": object()},
        available_data_levels={"BTCUSDT.BINANCE": frozenset({"BAR"})},
    )

    batch = candidate_generation.generate_research_candidates(
        _config(recipe_ids=("ema-cross-fast", "ema-cross-balanced")),
        dataset,
    )

    assert len(batch.candidates) == 4
    assert [call["recipe_id"] for call in calls] == [
        "ema-cross-fast",
        "ema-cross-fast",
        "ema-cross-balanced",
        "ema-cross-balanced",
    ]
    assert [call["seed"] for call in calls] == [5, 6, 5, 6]


def test_public_run_payload_records_recipe_identity_without_secrets() -> None:
    report = SimpleNamespace(
        run_id="run-recipe",
        generated=1,
        stored=1,
        paper_queued=0,
        resumed=False,
        finalists=(),
    )
    payload = research_job._public_run_payload(
        family="trend",
        recipe_id="ema-cross-fast",
        seed=5,
        timeframe="1h",
        report=report,
        manifests=(),
    )
    assert payload["recipe_id"] == "ema-cross-fast"
    assert payload["family"] == "trend"
