from mastertrd.research.generator import generate_candidate
from mastertrd.strategy_families import FAMILIES


def test_seeded_generation_is_reproducible():
    a = generate_candidate(family="trend", instruments=("BTCUSDT",), seed=42)
    b = generate_candidate(family="trend", instruments=("BTCUSDT",), seed=42)
    assert a.canonical_payload() == b.canonical_payload()
    assert a.genome_hash == b.genome_hash


def test_every_registered_family_can_generate_a_candidate():
    for index, family in enumerate(FAMILIES):
        genome = generate_candidate(family=family, instruments=("BTCUSDT", "ETHUSDT"), seed=index)
        assert genome.family == family
        assert genome.entry
        assert genome.exit
        assert genome.risk


def test_hft_family_declares_non_bar_data_requirement():
    genome = generate_candidate(family="market_making", instruments=("BTCUSDT",), seed=9)
    assert "L2" in genome.data_requirements


def test_regular_swing_candidate_stays_bar_based():
    genome = generate_candidate(family="swing", instruments=("BTCUSDT",), seed=9)
    assert genome.data_requirements == ("BAR",)


def test_seed_changes_candidate_structure_or_parameters():
    a = generate_candidate(family="momentum", instruments=("BTCUSDT",), seed=1)
    b = generate_candidate(family="momentum", instruments=("BTCUSDT",), seed=2)
    assert a.genome_hash != b.genome_hash
