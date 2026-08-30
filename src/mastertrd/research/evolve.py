from __future__ import annotations

from dataclasses import replace
from math import isfinite
from numbers import Integral, Real
from typing import Callable, Sequence

import numpy as np

from mastertrd.genome import StrategyGenome


_MUTABLE_SECTIONS = ("entry", "exit", "filters", "risk")


def _score_vector(value: float | Sequence[float]) -> tuple[float, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        scores = tuple(float(item) for item in value)
    else:
        scores = (float(value),)
    if not scores or not all(isfinite(item) for item in scores):
        raise ValueError("evolution objective must return finite scores")
    return scores


def _validate_seed_contract(seeds: Sequence[StrategyGenome]) -> StrategyGenome:
    if not seeds:
        raise ValueError("at least one seed genome is required")
    base = seeds[0]
    for genome in seeds[1:]:
        if genome.family != base.family:
            raise ValueError("seed genomes must belong to one family")
        if tuple(genome.instruments) != tuple(base.instruments):
            raise ValueError("seed genomes must target the same instruments")
        if tuple(genome.data_requirements) != tuple(base.data_requirements):
            raise ValueError("seed genomes must preserve data requirements")
    return base


def _numeric_coordinates(seeds: Sequence[StrategyGenome]):
    base = seeds[0]
    coords: list[tuple[str, str, bool, float, float]] = []
    for section in _MUTABLE_SECTIONS:
        base_values = getattr(base, section)
        for key, first_value in base_values.items():
            if isinstance(first_value, bool) or not isinstance(first_value, Real):
                continue
            observed: list[float] = []
            compatible = True
            for genome in seeds:
                value = getattr(genome, section).get(key)
                if isinstance(value, bool) or not isinstance(value, Real):
                    compatible = False
                    break
                observed.append(float(value))
            if not compatible:
                continue
            low, high = min(observed), max(observed)
            if low == high:
                # Keep constant schema values out of the search surface.
                continue
            coords.append((section, key, isinstance(first_value, Integral), low, high))
    return coords


def _materialize(base: StrategyGenome, coords, vector) -> StrategyGenome:
    updates = {section: dict(getattr(base, section)) for section in _MUTABLE_SECTIONS}
    for (section, key, integer, low, high), raw in zip(coords, vector, strict=True):
        value = min(max(float(raw), low), high)
        updates[section][key] = int(round(value)) if integer else float(value)

    entry = updates["entry"]
    # Preserve the most important structural ordering invariant used by several
    # bar families. This is a fail-closed repair within the observed seed bounds,
    # never a mutation of the execution/data contract.
    fast_key = "fast" if "fast" in entry else "fast_period" if "fast_period" in entry else None
    slow_key = "slow" if "slow" in entry else "slow_period" if "slow_period" in entry else None
    if fast_key and slow_key and float(entry[fast_key]) >= float(entry[slow_key]):
        return base

    return replace(
        base,
        entry=updates["entry"],
        exit=updates["exit"],
        filters=updates["filters"],
        risk=updates["risk"],
    )


def evolve_genomes(
    seed_genomes: Sequence[StrategyGenome],
    objective: Callable[[StrategyGenome], float | Sequence[float]],
    *,
    generations: int,
    population: int,
    seed: int,
) -> tuple[StrategyGenome, ...]:
    """Evolve only numeric parameters already admitted by the seed family schema.

    Lifecycle identity, instruments, timeframe and data requirements are copied
    from the first seed and cannot be mutated by the optimizer.
    """
    if generations <= 0:
        raise ValueError("generations must be positive")
    if population <= 1:
        raise ValueError("population must be greater than one")

    seeds = tuple(seed_genomes)
    base = _validate_seed_contract(seeds)
    coords = _numeric_coordinates(seeds)
    if not coords:
        return (base,)

    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.algorithms.soo.nonconvex.ga import GA
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.optimize import minimize

    dimensions = len(_score_vector(objective(base)))
    lower = np.asarray([item[3] for item in coords], dtype=float)
    upper = np.asarray([item[4] for item in coords], dtype=float)

    class GenomeProblem(ElementwiseProblem):
        def __init__(self) -> None:
            super().__init__(n_var=len(coords), n_obj=dimensions, xl=lower, xu=upper)

        def _evaluate(self, x, out, *args, **kwargs) -> None:
            genome = _materialize(base, coords, x)
            scores = _score_vector(objective(genome))
            if len(scores) != dimensions:
                raise ValueError("evolution objective dimensionality changed")
            # pymoo minimizes; MasterTrd research objectives use higher-is-better.
            out["F"] = [-score for score in scores] if dimensions > 1 else -scores[0]

    algorithm = GA(pop_size=population) if dimensions == 1 else NSGA2(pop_size=population)
    result = minimize(
        GenomeProblem(),
        algorithm,
        ("n_gen", generations),
        seed=seed,
        verbose=False,
        save_history=False,
    )
    if result.X is None:
        raise RuntimeError("pymoo returned no evolved genomes")

    vectors = np.atleast_2d(result.X)
    candidates = [_materialize(base, coords, vector) for vector in vectors]
    candidates.extend(seeds)

    unique: dict[str, StrategyGenome] = {}
    for genome in candidates:
        unique[genome.genome_hash] = genome

    ranked = sorted(
        unique.values(),
        key=lambda genome: _score_vector(objective(genome)),
        reverse=True,
    )
    return tuple(ranked[: max(1, min(population, len(ranked)))])
