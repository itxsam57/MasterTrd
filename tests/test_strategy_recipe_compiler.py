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



def test_family_generator_and_named_recipe_compiler_have_distinct_ownership() -> None:
    generated = generate_candidate(
        family="trend",
        instruments=("BTCUSDT.BINANCE",),
        seed=13,
    )
    compiled = compile_strategy_recipe(
        "ema-cross-balanced",
        instruments=("BTCUSDT.BINANCE",),
        seed=13,
    )

    assert generated.style == "trend"
    assert compiled.style == "recipe:ema-cross-balanced"
    assert generated.strategy_id != compiled.strategy_id


@pytest.mark.parametrize(
    ("recipe_id", "entry_kind", "exit_kind"),
    [
        ("trend-05", "macd_trend", "cross_reverse"),
        ("momentum-10", "absolute_momentum", "atr_bracket"),
        ("reversion-01", "bollinger_reversion", "mean_or_atr_stop"),
        ("reversion-02", "rsi_reversion", "mean_or_atr_stop"),
        ("breakout-03", "bollinger_squeeze_breakout", "atr_bracket"),
    ],
)
def test_promoted_catalog_recipes_compile_to_distinct_exact_semantics(recipe_id, entry_kind, exit_kind) -> None:
    genome = compile_strategy_recipe(
        recipe_id,
        instruments=("BTCUSDT.BINANCE",),
        seed=17,
    )
    assert genome.entry["type"] == entry_kind
    assert genome.exit["type"] == exit_kind
    assert genome.style == f"recipe:{recipe_id}"
