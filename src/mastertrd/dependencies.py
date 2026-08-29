from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DependencySpec:
    key: str
    module: str
    role: str
    required_for_core: bool = False


DEPENDENCIES: Mapping[str, DependencySpec] = {
    "nautilus": DependencySpec("nautilus", "nautilus_trader", "authoritative backtest/execution"),
    "vectorbt": DependencySpec("vectorbt", "vectorbt", "fast strategy screening"),
    "optuna": DependencySpec("optuna", "optuna", "parameter optimization"),
    "pymoo": DependencySpec("pymoo", "pymoo", "evolutionary structural search"),
    "duckdb": DependencySpec("duckdb", "duckdb", "research memory/query engine"),
    "pyarrow": DependencySpec("pyarrow", "pyarrow", "Parquet data interchange"),
    "statsmodels": DependencySpec("statsmodels", "statsmodels", "statistical arbitrage/tests"),
    "arch": DependencySpec("arch", "arch", "volatility/GARCH/bootstrap research"),
    "ruptures": DependencySpec("ruptures", "ruptures", "historical regime detection"),
    "river": DependencySpec("river", "river", "online drift detection"),
    "skfolio": DependencySpec("skfolio", "skfolio", "robust validation/portfolio selection"),
    "quantstats": DependencySpec("quantstats", "quantstats", "independent performance analytics"),
    "hftbacktest": DependencySpec("hftbacktest", "hftbacktest", "HFT queue/latency validation"),
    "talib": DependencySpec("talib", "talib", "research indicator implementations"),
    "ccxt": DependencySpec("ccxt", "ccxt", "historical-data fallback only"),
}


def dependency_availability() -> dict[str, bool]:
    return {key: importlib.util.find_spec(spec.module) is not None for key, spec in DEPENDENCIES.items()}
