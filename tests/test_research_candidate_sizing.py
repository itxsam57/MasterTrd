from types import SimpleNamespace

import mastertrd.research_candidate_generation as candidate_generation
from mastertrd.research.generator import generate_candidate


def test_explicit_trade_size_is_bound_into_generated_candidate_identity() -> None:
    small = generate_candidate(
        family="trend",
        instruments=("BTCUSDT.BINANCE",),
        seed=42,
        trade_size="0.01000",
    )
    large = generate_candidate(
        family="trend",
        instruments=("BTCUSDT.BINANCE",),
        seed=42,
        trade_size="0.02000",
    )

    assert small.entry["trade_size"] == "0.01000"
    assert large.entry["trade_size"] == "0.02000"
    assert small.genome_hash != large.genome_hash


def test_research_generation_preserves_configured_trade_size(monkeypatch) -> None:
    monkeypatch.setattr(
        candidate_generation,
        "family_instrument_sets",
        lambda *_args, **_kwargs: (("BTCUSDT.BINANCE",),),
    )
    config = SimpleNamespace(
        families=("trend",),
        instruments=("BTCUSDT.BINANCE",),
        seed_start=42,
        seed_stop=43,
        trade_size="0.01000",
    )
    dataset = SimpleNamespace(
        nautilus_instruments={"BTCUSDT.BINANCE": object()},
        available_data_levels={"BTCUSDT.BINANCE": frozenset({"BAR"})},
    )

    batch = candidate_generation.generate_research_candidates(config, dataset)

    assert len(batch.candidates) == 1
    assert batch.candidates[0].entry["trade_size"] == config.trade_size
