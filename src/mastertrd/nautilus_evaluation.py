from __future__ import annotations

from importlib.metadata import version
from math import isfinite, prod
from statistics import mean, stdev
from typing import Iterable, Sequence

from .contracts import EvaluationResult
from .genome import StrategyGenome
from .nautilus_backtest import _build_binance_spot_engine
from .nautilus_strategy import compile_genome_to_nautilus


def _finite(value: float, default: float = 0.0) -> float:
    result = float(value)
    return result if isfinite(result) else default


def _return_metrics(values: Iterable[float]) -> tuple[float, float, float, float, float]:
    returns = [_finite(value) for value in values]
    if not returns:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    total_return = prod(1.0 + value for value in returns) - 1.0
    average = mean(returns)
    volatility = stdev(returns) if len(returns) > 1 else 0.0
    sharpe = average / volatility if volatility > 0.0 else 0.0

    downside = [value for value in returns if value < 0.0]
    downside_deviation = stdev(downside) if len(downside) > 1 else 0.0
    sortino = average / downside_deviation if downside_deviation > 0.0 else 0.0

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    gains = sum(value for value in returns if value > 0.0)
    losses = abs(sum(value for value in returns if value < 0.0))
    profit_factor = gains / losses if losses > 0.0 else (1.0 if gains > 0.0 else 0.0)

    return (
        _finite(total_return),
        _finite(sharpe),
        _finite(sortino),
        abs(_finite(max_drawdown)),
        _finite(profit_factor),
    )


def run_binance_spot_evaluation(
    *,
    genome: StrategyGenome,
    instrument,
    data: Iterable[object],
    dataset_hash: str,
    code_hash: str,
    fees: float = 0.0,
    slippage: float = 0.0,
    starting_balances: Sequence[str] = ("100000 USDT",),
    trade_size_override: str | None = None,
) -> EvaluationResult:
    if not dataset_hash or not code_hash:
        raise ValueError("dataset_hash and code_hash are required")
    if not isfinite(float(fees)) or not isfinite(float(slippage)):
        raise ValueError("fees and slippage must be finite")
    if fees < 0.0 or slippage < 0.0:
        raise ValueError("fees and slippage cannot be negative")

    events = list(data)
    if not events:
        raise ValueError("historical data is required")

    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size_override=trade_size_override,
    )
    engine = _build_binance_spot_engine(
        instrument=instrument,
        starting_balances=starting_balances,
    )
    try:
        engine.add_data(events)
        engine.add_strategy(strategy)
        engine.run()

        # Stable NautilusTrader 1.231 exposes completed position state through the
        # cache, while BacktestResult does not expose the newer returns_series API.
        # position.realized_return already contains Nautilus's native simulated
        # instrument commissions. ``fees`` and ``slippage`` are additional,
        # deterministic research-stress fractions applied per completed round trip;
        # this makes robustness reruns materially harsher without pretending they
        # changed the historical market path or the strategy's trade decisions.
        closed_positions = engine.cache.positions_closed()
        raw_returns = [float(position.realized_return) for position in closed_positions]
        stress_drag = float(fees) + float(slippage)
        stressed_returns = [value - stress_drag for value in raw_returns]
        trade_count = len(closed_positions)

        total_return, sharpe, sortino, max_drawdown, profit_factor = _return_metrics(stressed_returns)
        expectancy = mean(stressed_returns) if stressed_returns else 0.0

        return EvaluationResult(
            strategy_id=genome.strategy_id,
            genome_hash=genome.genome_hash,
            dataset_hash=dataset_hash,
            code_hash=code_hash,
            engine="nautilus_trader",
            engine_version=version("nautilus_trader"),
            total_return=total_return,
            sharpe=sharpe,
            sortino=sortino,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            expectancy=_finite(expectancy),
            trade_count=trade_count,
            turnover=0.0,
            fees=float(fees),
            slippage=float(slippage),
            scores={"execution_backtest": 1.0 if trade_count > 0 else 0.0},
        )
    finally:
        engine.dispose()
