from __future__ import annotations

import pytest

from mastertrd.strategy_families import FAMILIES
from mastertrd.strategy_universe import (
    AssetClass,
    RecipeReadiness,
    STRATEGY_RECIPES,
    STRATEGY_SOURCES,
    recipes_for,
    strategy_recipe,
)


def test_strategy_universe_has_broad_unique_catalog() -> None:
    recipe_ids = [recipe.recipe_id for recipe in STRATEGY_RECIPES]
    source_ids = [source.source_id for source in STRATEGY_SOURCES]

    assert len(STRATEGY_RECIPES) >= 100
    assert len(set(recipe_ids)) == len(recipe_ids)
    assert len(set(source_ids)) == len(source_ids)
    assert sum(recipe.readiness is RecipeReadiness.EXECUTABLE for recipe in STRATEGY_RECIPES) >= 30


def test_every_recipe_resolves_sources_family_and_blocker_contract() -> None:
    source_ids = {source.source_id for source in STRATEGY_SOURCES}

    for recipe in STRATEGY_RECIPES:
        assert recipe.family in FAMILIES
        assert recipe.source_ids
        assert set(recipe.source_ids).issubset(source_ids)
        assert recipe.asset_classes
        assert recipe.horizons
        if recipe.readiness is RecipeReadiness.EXECUTABLE:
            assert recipe.entry_kind
            assert recipe.exit_kind
            assert recipe.blocker is None
        else:
            assert recipe.blocker


def test_catalog_spans_required_asset_classes() -> None:
    covered = {
        asset_class
        for recipe in STRATEGY_RECIPES
        for asset_class in recipe.asset_classes
    }
    assert {
        AssetClass.CRYPTO,
        AssetClass.EQUITY,
        AssetClass.FX,
        AssetClass.FUTURES,
        AssetClass.COMMODITY,
        AssetClass.RATES,
        AssetClass.OPTIONS,
        AssetClass.PREDICTION,
        AssetClass.BETTING,
        AssetClass.MULTI_ASSET,
    }.issubset(covered)


def test_strategy_recipe_lookup_and_filters_are_deterministic() -> None:
    trend = recipes_for(family="trend")
    executable_crypto = recipes_for(
        asset_class=AssetClass.CRYPTO,
        readiness=RecipeReadiness.EXECUTABLE,
    )

    assert trend
    assert executable_crypto
    assert trend == recipes_for(family="trend")
    assert executable_crypto == recipes_for(
        asset_class=AssetClass.CRYPTO,
        readiness=RecipeReadiness.EXECUTABLE,
    )
    assert strategy_recipe(trend[0].recipe_id) == trend[0]

    with pytest.raises(ValueError, match="unknown strategy recipe"):
        strategy_recipe("missing-recipe")


def test_basis_recipes_require_admitted_specialist_market_state() -> None:
    expected = {
        "crypto-funding-basis": "qualifying_funding_basis_market_state_required",
        "crypto-hedged-basis": "qualifying_hedge_drift_market_state_required",
    }
    for recipe_id, blocker in expected.items():
        recipe = strategy_recipe(recipe_id)
        assert recipe.readiness is RecipeReadiness.SPECIALIST_DATA_REQUIRED
        assert recipe.blocker == blocker
