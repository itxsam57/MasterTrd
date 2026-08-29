from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class IntegerOptimizationResult:
    name: str
    best_value: int
    best_score: float
    trials_completed: int


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
