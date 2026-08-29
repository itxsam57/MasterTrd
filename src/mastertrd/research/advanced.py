from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class EvolutionResult:
    best_value: float
    best_loss: float


@dataclass(frozen=True, slots=True)
class IndependentMetrics:
    sharpe: float
    sortino: float
    max_drawdown: float


def evolve_continuous_parameter(
    *,
    low: float,
    high: float,
    generations: int,
    population: int,
    seed: int,
    objective: Callable[[float], float],
) -> EvolutionResult:
    if low >= high:
        raise ValueError("low must be less than high")
    if generations <= 0 or population <= 1:
        raise ValueError("generations and population must be positive")

    from pymoo.algorithms.soo.nonconvex.ga import GA
    from pymoo.core.problem import ElementwiseProblem
    from pymoo.optimize import minimize

    class OneParameterProblem(ElementwiseProblem):
        def __init__(self) -> None:
            super().__init__(n_var=1, n_obj=1, xl=[low], xu=[high])

        def _evaluate(self, x, out, *args, **kwargs) -> None:
            out["F"] = float(objective(float(x[0])))

    result = minimize(
        OneParameterProblem(),
        GA(pop_size=population),
        ("n_gen", generations),
        seed=seed,
        verbose=False,
    )
    if result.X is None or result.F is None:
        raise RuntimeError("pymoo returned no solution")
    return EvolutionResult(
        best_value=float(result.X[0]),
        best_loss=float(result.F[0]),
    )


def detect_online_drift(values: Iterable[float]) -> list[int]:
    from river import drift

    detector = drift.ADWIN()
    change_points: list[int] = []
    for index, value in enumerate(values):
        detector.update(float(value))
        if detector.drift_detected:
            change_points.append(index)
    return change_points


def walk_forward_splits(
    X,
    *,
    train_size: int,
    test_size: int,
    purged_size: int = 1,
) -> list[tuple[object, object]]:
    from skfolio.model_selection import WalkForward

    cv = WalkForward(
        train_size=train_size,
        test_size=test_size,
        purged_size=purged_size,
    )
    return list(cv.split(X))


def independent_metrics(returns, *, periods: int) -> IndependentMetrics:
    if periods <= 0:
        raise ValueError("periods must be positive")

    import pandas as pd
    import quantstats as qs

    series = returns if isinstance(returns, pd.Series) else pd.Series(returns, dtype=float)
    if not isinstance(series.index, pd.DatetimeIndex):
        series = series.copy()
        series.index = pd.date_range("2000-01-01", periods=len(series), freq="D")

    return IndependentMetrics(
        sharpe=float(qs.stats.sharpe(series, periods=periods)),
        sortino=float(qs.stats.sortino(series, periods=periods)),
        max_drawdown=float(qs.stats.max_drawdown(series)),
    )
