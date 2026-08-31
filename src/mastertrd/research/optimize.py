from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from numbers import Integral, Real
from typing import Callable, Mapping, Sequence, Any

from mastertrd.genome import StrategyGenome


@dataclass(frozen=True, slots=True)
class IntegerOptimizationResult:
    name: str
    best_value: int
    best_score: float
    trials_completed: int


@dataclass(frozen=True, slots=True)
class GenomeOptimizationResult:
    best_genome: StrategyGenome
    best_scores: tuple[float, ...]
    trials_completed: int
    trials_rejected: int


def optimize_integer_parameter(
    *,
    name: str,
    low: int,
    high: int,
    trials: int,
    seed: int,
    objective: Callable[[int], float],
) -> IntegerOptimizationResult:
    if not name:
        raise ValueError("name is required")
    if low > high:
        raise ValueError("low cannot exceed high")
    if trials <= 0:
        raise ValueError("trials must be positive")

    import optuna

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)

    def wrapped(trial: optuna.Trial) -> float:
        value = trial.suggest_int(name, low, high)
        return float(objective(value))

    study.optimize(wrapped, n_trials=trials, show_progress_bar=False)
    completed = sum(t.state is optuna.trial.TrialState.COMPLETE for t in study.trials)
    return IntegerOptimizationResult(
        name=name,
        best_value=int(study.best_params[name]),
        best_score=float(study.best_value),
        trials_completed=completed,
    )


def _replace_path(genome: StrategyGenome, path: str, value: Any) -> StrategyGenome:
    try:
        section, key = path.split(".", 1)
    except ValueError as exc:
        raise ValueError(f"parameter path must be section.key: {path}") from exc
    if section not in {"entry", "exit", "filters", "risk"}:
        raise ValueError(f"protected or unsupported parameter section: {section}")
    current = dict(getattr(genome, section))
    if key not in current:
        raise ValueError(f"parameter does not exist in genome schema: {path}")
    current[key] = value
    return replace(genome, **{section: current})


def _suggest(trial, name: str, spec: object) -> object:
    if isinstance(spec, tuple) and len(spec) == 2:
        low, high = spec
        if isinstance(low, Integral) and not isinstance(low, bool) and isinstance(high, Integral) and not isinstance(high, bool):
            if int(low) > int(high):
                raise ValueError(f"invalid integer bounds for {name}")
            return trial.suggest_int(name, int(low), int(high))
        if isinstance(low, Real) and isinstance(high, Real):
            if not isfinite(float(low)) or not isfinite(float(high)) or float(low) > float(high):
                raise ValueError(f"invalid float bounds for {name}")
            return trial.suggest_float(name, float(low), float(high))
        raise ValueError(f"numeric bounds required for {name}")
    if isinstance(spec, Sequence) and not isinstance(spec, (str, bytes, bytearray)):
        choices = list(spec)
        if not choices:
            raise ValueError(f"categorical space cannot be empty: {name}")
        return trial.suggest_categorical(name, choices)
    raise ValueError(f"unsupported parameter space for {name}")


def _scores(value: object) -> tuple[float, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = tuple(float(item) for item in value)
    else:
        result = (float(value),)
    if not result or not all(isfinite(item) for item in result):
        raise ValueError("objective scores must be finite")
    return result


def optimize_genome(
    base_genome: StrategyGenome,
    parameter_space: Mapping[str, object],
    objective: Callable[[StrategyGenome], float | Sequence[float]],
    *,
    trials: int,
    seed: int,
    constraints: Sequence[Callable[[StrategyGenome], bool]] = (),
) -> GenomeOptimizationResult:
    """Optimize mutable genome parameters while preserving its execution contract.

    Only entry/exit/filter/risk keys already present on ``base_genome`` are mutable.
    Instrument identity, family, timeframe and data requirements are intentionally
    outside the parameter surface and therefore cannot be optimized away.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not parameter_space:
        raise ValueError("parameter_space is required")

    import optuna

    # Determine objective dimensionality without changing the genome. This also
    # fail-fast validates the objective before an expensive study is created.
    dimensions = len(_scores(objective(base_genome)))
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(
        directions=["maximize"] * dimensions if dimensions > 1 else None,
        direction="maximize" if dimensions == 1 else None,
        sampler=sampler,
    )

    genomes: dict[int, StrategyGenome] = {}

    def wrapped(trial: optuna.Trial):
        candidate = base_genome
        for path, spec in parameter_space.items():
            candidate = _replace_path(candidate, path, _suggest(trial, path, spec))
        if any(not check(candidate) for check in constraints):
            raise optuna.TrialPruned("hard genome constraint rejected candidate")
        values = _scores(objective(candidate))
        if len(values) != dimensions:
            raise ValueError("objective dimensionality changed between trials")
        genomes[trial.number] = candidate
        return values[0] if dimensions == 1 else values

    study.optimize(wrapped, n_trials=trials, show_progress_bar=False)
    completed_trials = [t for t in study.trials if t.state is optuna.trial.TrialState.COMPLETE]
    rejected = sum(t.state is optuna.trial.TrialState.PRUNED for t in study.trials)
    if not completed_trials:
        raise RuntimeError("no genome satisfied the optimization constraints")

    if dimensions == 1:
        best_trial = study.best_trial
        best_scores = (float(best_trial.value),)
    else:
        # Select a deterministic representative from the Pareto set. The full
        # objective vector is retained in the result; lexicographic selection
        # avoids arbitrary dependence on Optuna's internal Pareto ordering.
        best_trial = max(study.best_trials, key=lambda t: tuple(float(v) for v in (t.values or ())))
        best_scores = tuple(float(v) for v in (best_trial.values or ()))

    return GenomeOptimizationResult(
        best_genome=genomes[best_trial.number],
        best_scores=best_scores,
        trials_completed=len(completed_trials),
        trials_rejected=rejected,
    )
