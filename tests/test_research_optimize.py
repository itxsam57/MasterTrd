from mastertrd.research.generator import generate_candidate
from mastertrd.research.optimize import optimize_genome


def test_optimizer_respects_parameter_bounds_and_keeps_genome_valid():
    base = generate_candidate(family="trend", instruments=("ETHUSDT",), seed=3)
    result = optimize_genome(
        base,
        {
            "entry.fast": (5, 20),
            "entry.slow": (30, 100),
            "risk.risk_fraction": (0.001, 0.01),
            "filters.adx_min": [15, 20, 25, 30],
        },
        objective=lambda genome: -abs(int(genome.entry["fast"]) - 10),
        trials=16,
        seed=7,
    )

    assert 5 <= result.best_genome.entry["fast"] <= 20
    assert 30 <= result.best_genome.entry["slow"] <= 100
    assert 0.001 <= result.best_genome.risk["risk_fraction"] <= 0.01
    assert result.best_genome.filters["adx_min"] in {15, 20, 25, 30}
    assert result.best_genome.instruments == base.instruments
    assert result.best_genome.data_requirements == base.data_requirements
    assert result.trials_completed > 0


def test_optimizer_supports_score_vectors_and_hard_constraint_rejection():
    base = generate_candidate(family="trend", instruments=("ETHUSDT",), seed=4)

    result = optimize_genome(
        base,
        {"entry.fast": (5, 20), "entry.slow": (21, 40)},
        objective=lambda genome: (
            float(genome.entry["fast"]),
            -float(genome.entry["slow"]),
        ),
        trials=12,
        seed=8,
        constraints=(lambda genome: int(genome.entry["fast"]) < int(genome.entry["slow"]),),
    )

    assert int(result.best_genome.entry["fast"]) < int(result.best_genome.entry["slow"])
    assert len(result.best_scores) == 2
