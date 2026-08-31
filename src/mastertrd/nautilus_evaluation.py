from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version
from math import isfinite, prod
from statistics import mean, stdev
from typing import Iterable, Sequence

from .contracts import EvaluationResult
from .genome import StrategyGenome
from .nautilus_strategy import compile_genome_to_nautilus
from .product_contracts import validate_product_compatibility
from .risk_profiles import build_research_backtest_risk_runtime
from .risk_runtime import RiskRuntime


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


def _event_instrument_id(event: object) -> str:
    instrument_id = getattr(event, "instrument_id", None)
    if instrument_id is None:
        bar_type = getattr(event, "bar_type", None)
        instrument_id = getattr(bar_type, "instrument_id", None)
    value = getattr(instrument_id, "value", None)
    if not isinstance(value, str) or not value:
        raise ValueError("historical event is missing a concrete Nautilus instrument id")
    return value


def _normalize_evaluation_inputs(
    genome: StrategyGenome,
    instruments: Mapping[str, object],
    data_by_instrument: Mapping[str, Iterable[object]],
) -> tuple[dict[str, object], dict[str, tuple[object, ...]]]:
    validate_product_compatibility(genome, instruments)
    if not isinstance(data_by_instrument, Mapping):
        raise ValueError("data_by_instrument mapping is required")

    expected = tuple(genome.instruments)
    expected_set = set(expected)
    supplied_set = set(data_by_instrument)
    missing = [instrument_id for instrument_id in expected if instrument_id not in supplied_set]
    if missing:
        raise ValueError(f"missing historical data for: {', '.join(missing)}")
    extras = sorted(supplied_set - expected_set)
    if extras:
        raise ValueError(f"unexpected historical data for: {', '.join(extras)}")

    ordered_instruments = {instrument_id: instruments[instrument_id] for instrument_id in expected}
    normalized_data: dict[str, tuple[object, ...]] = {}
    for instrument_id in expected:
        events = tuple(data_by_instrument[instrument_id])
        if not events:
            raise ValueError(f"historical data is required for {instrument_id}")
        mismatched = [
            _event_instrument_id(event)
            for event in events
            if _event_instrument_id(event) != instrument_id
        ]
        if mismatched:
            raise ValueError(
                f"historical data instrument mismatch for {instrument_id}: {mismatched[0]}",
            )
        normalized_data[instrument_id] = events
    return ordered_instruments, normalized_data


def _build_evaluation_engine(
    *,
    instruments: Mapping[str, object],
    starting_balances: Sequence[str],
):
    if not starting_balances:
        raise ValueError("at least one starting balance is required")

    venue_names = {instrument.id.venue.value for instrument in instruments.values()}
    if len(venue_names) != 1:
        raise ValueError(
            "generalized bar evaluation requires one venue; cross-venue candidates require the specialist HFT path",
        )
    venue_name = next(iter(venue_names))

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.instruments import CurrencyPair
    from nautilus_trader.model.objects import Money

    all_spot = all(isinstance(instrument, CurrencyPair) for instrument in instruments.values())
    account_type = AccountType.CASH if all_spot else AccountType.MARGIN

    engine = BacktestEngine(config=BacktestEngineConfig())
    engine.add_venue(
        venue=Venue(venue_name),
        oms_type=OmsType.NETTING,
        account_type=account_type,
        base_currency=None,
        starting_balances=[Money.from_str(value) for value in starting_balances],
    )
    for instrument in instruments.values():
        engine.add_instrument(instrument)
    return engine


def run_nautilus_evaluation(
    *,
    genome: StrategyGenome,
    instruments: Mapping[str, object],
    data_by_instrument: Mapping[str, Iterable[object]],
    dataset_hash: str,
    code_hash: str,
    fees: float = 0.0,
    slippage: float = 0.0,
    starting_balances: Sequence[str] = ("100000 USDT",),
    trade_size_override: str | None = None,
    risk_runtime: RiskRuntime | None = None,
) -> EvaluationResult:
    if not dataset_hash or not code_hash:
        raise ValueError("dataset_hash and code_hash are required")
    if not isfinite(float(fees)) or not isfinite(float(slippage)):
        raise ValueError("fees and slippage must be finite")
    if fees < 0.0 or slippage < 0.0:
        raise ValueError("fees and slippage cannot be negative")

    ordered_instruments, normalized_data = _normalize_evaluation_inputs(
        genome,
        instruments,
        data_by_instrument,
    )

    evaluation_risk = risk_runtime or build_research_backtest_risk_runtime()
    primary = ordered_instruments[genome.instruments[0]]
    strategy = compile_genome_to_nautilus(
        genome,
        instrument=primary,
        instrument_map=ordered_instruments if len(ordered_instruments) > 1 else None,
        trade_size_override=trade_size_override,
        risk_runtime=evaluation_risk,
    )
    engine = _build_evaluation_engine(
        instruments=ordered_instruments,
        starting_balances=starting_balances,
    )
    try:
        # Stable Nautilus low-level backtesting treats each add_data call as an
        # independently ordered stream and merges all streams chronologically.
        for instrument_id in genome.instruments:
            engine.add_data(normalized_data[instrument_id])
        engine.add_strategy(strategy)
        engine.run()

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
    risk_runtime: RiskRuntime | None = None,
) -> EvaluationResult:
    """Backward-compatible single-instrument wrapper over the generalized evaluator."""
    instrument_id = instrument.id.value
    return run_nautilus_evaluation(
        genome=genome,
        instruments={instrument_id: instrument},
        data_by_instrument={instrument_id: tuple(data)},
        dataset_hash=dataset_hash,
        code_hash=code_hash,
        fees=fees,
        slippage=slippage,
        starting_balances=starting_balances,
        trade_size_override=trade_size_override,
        risk_runtime=risk_runtime,
    )
