from __future__ import annotations

import pytest

from mastertrd.research.generator import generate_candidate
from mastertrd.strategy_universe import compile_strategy_recipe, strategy_recipe


def test_recipe_compilation_is_deterministic_and_identity_bound() -> None:
    first = compile_strategy_recipe(
        "ema-cross-fast",
        instruments=("BTCUSDT.BINANCE",),
        seed=11,
    )
    second = compile_strategy_recipe(
        "ema-cross-fast",
        instruments=("BTCUSDT.BINANCE",),
        seed=11,
    )
    recipe = strategy_recipe("ema-cross-fast")

    assert first.canonical_payload() == second.canonical_payload()
    assert first.genome_hash == second.genome_hash
    assert first.entry["type"] == recipe.entry_kind
    assert first.exit["type"] == recipe.exit_kind
    assert first.family == recipe.family
    assert first.style == "recipe:ema-cross-fast"


def test_distinct_recipes_in_same_family_produce_distinct_genomes() -> None:
    fast = compile_strategy_recipe(
        "ema-cross-fast",
        instruments=("BTCUSDT.BINANCE",),
        seed=7,
    )
    slow = compile_strategy_recipe(
        "ema-cross-slow",
        instruments=("BTCUSDT.BINANCE",),
        seed=7,
    )

    assert fast.genome_hash != slow.genome_hash
    assert fast.strategy_id != slow.strategy_id


def test_recipe_compiler_validates_instrument_cardinality() -> None:
    with pytest.raises(ValueError, match="exactly 2 instruments"):
        compile_strategy_recipe(
            "pairs-cointegration-balanced",
            instruments=("BTCUSDT.BINANCE",),
            seed=5,
        )

    with pytest.raises(ValueError, match="exactly 1 instrument"):
        compile_strategy_recipe(
            "ema-cross-fast",
            instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
            seed=5,
        )


def test_recipe_compiler_preserves_trade_size_validation() -> None:
    genome = compile_strategy_recipe(
        "rsi-momentum-balanced",
        instruments=("BTCUSDT.BINANCE",),
        seed=9,
        trade_size="0.025",
    )
    assert genome.entry["trade_size"] == "0.025"

    with pytest.raises(ValueError, match="trade_size must be a positive decimal"):
        compile_strategy_recipe(
            "rsi-momentum-balanced",
            instruments=("BTCUSDT.BINANCE",),
            seed=9,
            trade_size="0",
        )


def test_non_executable_recipe_fails_closed_with_catalog_blocker() -> None:
    with pytest.raises(ValueError, match="exact_strategy_primitive_not_yet_implemented"):
        compile_strategy_recipe(
            "cross-sectional-momentum",
            instruments=("BTCUSDT.BINANCE",),
            seed=3,
        )


def test_generate_candidate_recipe_path_uses_compiler_and_legacy_path_is_unchanged() -> None:
    via_generator = generate_candidate(
        family="trend",
        instruments=("BTCUSDT.BINANCE",),
        seed=13,
        recipe_id="ema-cross-balanced",
    )
    direct = compile_strategy_recipe(
        "ema-cross-balanced",
        instruments=("BTCUSDT.BINANCE",),
        seed=13,
    )
    assert via_generator.canonical_payload() == direct.canonical_payload()

    legacy = generate_candidate(
        family="trend",
        instruments=("BTCUSDT.BINANCE",),
        seed=13,
    )
    assert legacy.style == "trend"

    with pytest.raises(ValueError, match="belongs to family momentum"):
        generate_candidate(
            family="trend",
            instruments=("BTCUSDT.BINANCE",),
            seed=13,
            recipe_id="rsi-momentum-balanced",
        )
