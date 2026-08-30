from mastertrd.research.generator import generate_candidate
from mastertrd.robustness_cycle import _parameter_neighbors


def test_parameter_neighbors_support_non_ema_bar_families_without_changing_contract():
    for family in ("momentum", "breakout", "mean_reversion", "volatility", "swing", "position"):
        candidate = generate_candidate(family=family, instruments=("ETHUSDT.BINANCE",), seed=42)
        neighbors = _parameter_neighbors(candidate)

        assert len(neighbors) >= 2
        assert len({neighbor.genome_hash for neighbor in neighbors}) == len(neighbors)
        for neighbor in neighbors:
            assert neighbor.strategy_id == candidate.strategy_id
            assert neighbor.family == candidate.family
            assert neighbor.style == candidate.style
            assert neighbor.instruments == candidate.instruments
            assert neighbor.timeframe == candidate.timeframe
            assert neighbor.data_requirements == candidate.data_requirements
            assert neighbor.allow_short == candidate.allow_short
            assert neighbor.genome_hash != candidate.genome_hash


def test_parameter_neighbors_preserve_fast_slow_ordering():
    candidate = generate_candidate(family="trend", instruments=("ETHUSDT.BINANCE",), seed=42)
    neighbors = _parameter_neighbors(candidate)

    assert neighbors
    for neighbor in neighbors:
        assert int(neighbor.entry["fast"]) < int(neighbor.entry["slow"])
