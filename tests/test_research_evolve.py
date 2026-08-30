from mastertrd.research.evolve import evolve_genomes
from mastertrd.research.generator import generate_candidate


def test_evolution_returns_valid_hash_stable_genomes_without_mutating_contract():
    seeds = tuple(
        generate_candidate(family="trend", instruments=("ETHUSDT",), seed=seed)
        for seed in (11, 12, 13)
    )

    evolved = evolve_genomes(
        seeds,
        objective=lambda genome: -abs(int(genome.entry["fast"]) - 10),
        generations=3,
        population=8,
        seed=99,
    )

    assert evolved
    for genome in evolved:
        assert genome.family == "trend"
        assert genome.instruments == seeds[0].instruments
        assert genome.data_requirements == seeds[0].data_requirements
        assert genome.timeframe == seeds[0].timeframe
        assert genome.genome_hash == genome.genome_hash
        assert int(genome.entry["fast"]) > 0
        assert int(genome.entry["fast"]) < int(genome.entry["slow"])
