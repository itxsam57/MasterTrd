from __future__ import annotations

from collections import Counter
from typing import Any

from .runtime import RuntimeConfig
from .strategy_universe import STRATEGY_RECIPES


class AppService:
    """Thin read model for the local consumer app and CLI."""

    def snapshot(self) -> dict[str, Any]:
        runtime = RuntimeConfig.from_env()
        readiness = Counter(recipe.readiness.value for recipe in STRATEGY_RECIPES)
        return {
            "mode": runtime.mode.value,
            "live_enabled": runtime.live_trading_enabled,
            "strategy_count": len(STRATEGY_RECIPES),
            "readiness": dict(sorted(readiness.items())),
        }

    def strategy_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "recipe_id": recipe.recipe_id,
                "name": recipe.name,
                "family": recipe.family,
                "readiness": recipe.readiness.value,
                "assets": [asset.value for asset in recipe.asset_classes],
                "horizons": [horizon.value for horizon in recipe.horizons],
                "blocker": recipe.blocker,
            }
            for recipe in STRATEGY_RECIPES
        ]
