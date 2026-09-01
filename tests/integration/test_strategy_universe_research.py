from __future__ import annotations

from types import SimpleNamespace

import pytest

from mastertrd.nautilus_evaluation import run_binance_spot_evaluation
from mastertrd.research_brain import (
    ResearchBrainConfig,
    generate_research_candidates,
    run_research_specialist_stage,
)
from mastertrd.strategy_universe import compile_strategy_recipe


def _config(*, family: str, recipe_id: str, instruments: tuple[str, ...]) -> ResearchBrainConfig:
    return ResearchBrainConfig(
        families=(family,),
        instruments=instruments,
        seed_start=11,
        seed_stop=12,
        screening_min_return=-1.0,
        optimization_trials=1,
        evolution_generations=1,
        evolution_population=2,
        validation_budget=1,
        paper_queue_cap=0,
        validation_window=50,
        recipe_ids=(recipe_id,),
    )


@pytest.mark.parametrize(
    ("recipe_id", "family"),
    (
        ("ema-cross-crypto", "trend"),
        ("donchian-crypto", "breakout"),
        ("zscore-crypto", "mean_reversion"),
    ),
)
def test_named_bar_recipes_enter_the_family_aware_research_candidate_path(recipe_id: str, family: str) -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    btc = TestInstrumentProvider.btcusdt_binance()
    eth = TestInstrumentProvider.ethusdt_binance()
    metadata = {btc.id.value: btc, eth.id.value: eth}
    dataset = SimpleNamespace(
        nautilus_instruments=metadata,
        available_data_levels={key: frozenset({"BAR"}) for key in metadata},
    )

    batch = generate_research_candidates(
        _config(family=family, recipe_id=recipe_id, instruments=tuple(metadata)),
        dataset,
    )

    assert batch.blockers == ()
    assert batch.candidates
    assert {candidate.family for candidate in batch.candidates} == {family}
    assert {candidate.style for candidate in batch.candidates} == {f"recipe:{recipe_id}"}
    assert all(len(candidate.instruments) == 1 for candidate in batch.candidates)


def test_named_stat_arb_recipe_uses_the_existing_multi_leg_universe_contract() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    btc = TestInstrumentProvider.btcusdt_binance()
    eth = TestInstrumentProvider.ethusdt_binance()
    metadata = {btc.id.value: btc, eth.id.value: eth}
    dataset = SimpleNamespace(
        nautilus_instruments=metadata,
        available_data_levels={key: frozenset({"BAR"}) for key in metadata},
    )

    batch = generate_research_candidates(
        _config(
            family="stat_arb",
            recipe_id="pairs-cointegration-balanced",
            instruments=tuple(metadata),
        ),
        dataset,
    )

    assert batch.blockers == ()
    assert batch.candidates
    assert {candidate.style for candidate in batch.candidates} == {"recipe:pairs-cointegration-balanced"}
    assert all(len(candidate.instruments) == 2 for candidate in batch.candidates)


def test_multi_leg_recipe_cannot_be_proxied_through_single_instrument_nautilus_wrapper() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    btc = TestInstrumentProvider.btcusdt_binance()
    eth = TestInstrumentProvider.ethusdt_binance()
    candidate = compile_strategy_recipe(
        "pairs-cointegration-balanced",
        instruments=(btc.id.value, eth.id.value),
        seed=23,
    )

    with pytest.raises(ValueError, match="missing instrument metadata"):
        run_binance_spot_evaluation(
            genome=candidate,
            instrument=btc,
            data=(),
            dataset_hash="multi-leg-proxy-regression",
            code_hash="strategy-universe-v1",
        )


def test_recipe_identity_survives_the_research_specialist_stage() -> None:
    candidate = compile_strategy_recipe(
        "ema-cross-crypto",
        instruments=("BTCUSDT.BINANCE",),
        seed=17,
    )

    artifact = run_research_specialist_stage(
        (
            {
                "genome": candidate.canonical_payload(),
                "passed": True,
                "score": 1.25,
                "reason": "nautilus_validated",
            },
        ),
        specialist_inputs_by_genome_hash={},
    )

    outcome = artifact["outcomes"][0]
    assert outcome["passed"] is True
    assert outcome["reason"] == "standard_execution_path"
    assert outcome["genome"]["style"] == "recipe:ema-cross-crypto"
    assert outcome["genome"]["genome_hash"] == candidate.genome_hash


@pytest.mark.parametrize(
    ("recipe_id", "blocker"),
    (
        ("options-iv-rv-defined-risk", "qualifying_option_chain_and_greeks_data_required"),
        ("inventory-skew-mm", "qualifying_real_l2_queue_latency_evidence_required"),
        ("polymarket-rv-01", "provider_not_admitted_to_mastertrd_runtime"),
    ),
)
def test_non_executable_specialist_or_provider_recipe_cannot_be_proxied_into_research(
    recipe_id: str,
    blocker: str,
) -> None:
    with pytest.raises(ValueError, match=blocker):
        compile_strategy_recipe(
            recipe_id,
            instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
            seed=19,
        )


def test_research_config_rejects_blocked_named_recipe_before_candidate_generation() -> None:
    with pytest.raises(ValueError, match="research recipe must be executable"):
        _config(
            family="options",
            recipe_id="options-iv-rv-defined-risk",
            instruments=("BTCUSDT.BINANCE",),
        )
