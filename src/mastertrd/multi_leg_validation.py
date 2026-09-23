from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import version
from math import isfinite
from typing import Sequence

from .genome import StrategyGenome
from .validation import ValidationEvidence


@dataclass(frozen=True, slots=True)
class MultiLegStressPolicy:
    min_completed_cycles: int
    max_leg_fill_skew: float
    max_residual_exposure_ratio: float
    max_slippage_bps: float

    def __post_init__(self) -> None:
        if self.min_completed_cycles <= 0:
            raise ValueError("min_completed_cycles must be positive")
        values = (
            self.max_leg_fill_skew,
            self.max_residual_exposure_ratio,
            self.max_slippage_bps,
        )
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("multi-leg policy thresholds must be finite")
        if not 0.0 <= self.max_leg_fill_skew <= 1.0:
            raise ValueError("max_leg_fill_skew must be between 0 and 1")
        if not 0.0 <= self.max_residual_exposure_ratio <= 1.0:
            raise ValueError("max_residual_exposure_ratio must be between 0 and 1")
        if self.max_slippage_bps < 0.0:
            raise ValueError("max_slippage_bps must be non-negative")


@dataclass(frozen=True, slots=True)
class MultiLegStressReport:
    strategy_id: str
    genome_hash: str
    dataset_hash: str
    code_hash: str
    engine: str
    engine_version: str
    expected_legs: int
    completed_cycles: int
    leg_fill_counts: Sequence[int]
    residual_exposure_ratio: float
    slippage_bps: float

    def __post_init__(self) -> None:
        identity = (
            self.strategy_id,
            self.genome_hash,
            self.dataset_hash,
            self.code_hash,
            self.engine,
            self.engine_version,
        )
        if not all(identity):
            raise ValueError("multi-leg report identity fields are required")
        if self.expected_legs < 2:
            raise ValueError("expected_legs must be at least 2")
        if len(self.leg_fill_counts) != self.expected_legs:
            raise ValueError("leg_fill_counts must match expected_legs")
        if self.completed_cycles < 0 or any(count < 0 for count in self.leg_fill_counts):
            raise ValueError("cycle and fill counts cannot be negative")
        if not isfinite(float(self.residual_exposure_ratio)) or not 0.0 <= self.residual_exposure_ratio <= 1.0:
            raise ValueError("residual_exposure_ratio must be finite and between 0 and 1")
        if not isfinite(float(self.slippage_bps)) or self.slippage_bps < 0.0:
            raise ValueError("slippage_bps must be finite and non-negative")


def _fill_skew(fill_counts: Sequence[int]) -> float:
    highest = max(fill_counts)
    if highest == 0:
        return 0.0
    return (highest - min(fill_counts)) / highest


def multi_leg_execution_stress_evidence(
    candidate: StrategyGenome,
    report: MultiLegStressReport,
    policy: MultiLegStressPolicy,
) -> ValidationEvidence:
    if report.strategy_id != candidate.strategy_id:
        raise ValueError("strategy_id does not match candidate")
    if report.genome_hash != candidate.genome_hash:
        raise ValueError("genome_hash does not match candidate")
    if len(candidate.instruments) < 2:
        raise ValueError("multi-leg validation requires at least two candidate instruments")
    if report.expected_legs != len(candidate.instruments):
        raise ValueError("expected_legs does not match candidate instruments")
    if report.engine != "nautilus_trader":
        raise ValueError("multi-leg execution stress must come from nautilus_trader")

    fill_skew = _fill_skew(report.leg_fill_counts)
    minimum_fill_count = min(report.leg_fill_counts)
    minimum_fill_ratio = (
        minimum_fill_count / report.completed_cycles
        if report.completed_cycles > 0
        else 0.0
    )
    required_fill_ratio = 1.0 - policy.max_leg_fill_skew
    passed = (
        report.completed_cycles >= policy.min_completed_cycles
        and minimum_fill_count > 0
        and fill_skew <= policy.max_leg_fill_skew
        and minimum_fill_ratio >= required_fill_ratio
        and report.residual_exposure_ratio <= policy.max_residual_exposure_ratio
        and report.slippage_bps <= policy.max_slippage_bps
    )

    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="multi_leg_execution_stress",
        dataset_hash=report.dataset_hash,
        code_hash=report.code_hash,
        engine=report.engine,
        engine_version=report.engine_version,
        passed=passed,
        metrics={
            "leg_count": float(report.expected_legs),
            "completed_cycles": float(report.completed_cycles),
            "minimum_leg_fill_count": float(minimum_fill_count),
            "minimum_leg_fill_ratio": float(minimum_fill_ratio),
            "leg_fill_skew": float(fill_skew),
            "residual_exposure_ratio": float(report.residual_exposure_ratio),
            "slippage_bps": float(report.slippage_bps),
        },
    )


def run_nautilus_multi_leg_stress(
    candidate: StrategyGenome,
    *,
    instruments: Mapping[str, object],
    data_by_instrument: Mapping[str, Iterable[object]],
    dataset_hash: str,
    code_hash: str,
    trade_size: str,
    starting_balances: Sequence[str] = ("100000 USDT",),
) -> MultiLegStressReport:
    """Execute a real Nautilus multi-leg replay and summarize leg execution integrity.

    This producer is intentionally execution-focused. It does not infer alpha and it
    never fabricates specialist evidence: every completed leg cycle comes from an
    actual closed Nautilus position, and slippage is measured from actual filled
    order prices against the exact input BAR close at the fill timestamp.
    """
    if len(candidate.instruments) < 2:
        raise ValueError("multi-leg stress requires at least two candidate instruments")
    if not dataset_hash or not code_hash:
        raise ValueError("dataset_hash and code_hash are required")
    expected = tuple(candidate.instruments)
    if set(instruments) != set(expected):
        raise ValueError("multi-leg stress instruments must match candidate exactly")
    if set(data_by_instrument) != set(expected):
        raise ValueError("multi-leg stress data must match candidate exactly")
    if not starting_balances:
        raise ValueError("multi-leg stress starting balances are required")

    from .nautilus_evaluation import _build_evaluation_engine
    from .nautilus_strategy import compile_genome_to_nautilus
    from .risk_profiles import build_research_backtest_risk_runtime

    materialized: dict[str, tuple[object, ...]] = {}
    reference_close: dict[tuple[str, int], float] = {}
    for instrument_id in expected:
        events = tuple(data_by_instrument[instrument_id])
        if not events:
            raise ValueError(f"multi-leg stress data is empty for {instrument_id}")
        for event in events:
            bar_type = getattr(event, "bar_type", None)
            observed_id = getattr(getattr(bar_type, "instrument_id", None), "value", None)
            if observed_id != instrument_id:
                raise ValueError(
                    f"multi-leg stress data instrument mismatch for {instrument_id}: {observed_id}"
                )
            try:
                ts_event = int(event.ts_event)
                close = float(event.close.as_double())
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("multi-leg stress requires concrete Nautilus BAR data") from exc
            if not isfinite(close) or close <= 0.0:
                raise ValueError("multi-leg stress BAR close must be positive and finite")
            reference_close[(instrument_id, ts_event)] = close
        materialized[instrument_id] = events

    primary = instruments[expected[0]]
    strategy = compile_genome_to_nautilus(
        candidate,
        instrument=primary,
        instrument_map=dict(instruments),
        trade_size_override=trade_size,
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    engine = _build_evaluation_engine(
        instruments=instruments,
        starting_balances=starting_balances,
    )
    try:
        for instrument_id in expected:
            engine.add_data(list(materialized[instrument_id]))
        engine.add_strategy(strategy)
        engine.run()

        closed_counts = Counter(
            position.instrument_id.value
            for position in engine.cache.positions_closed()
            if position.instrument_id.value in expected
        )
        leg_fill_counts = tuple(int(closed_counts[instrument_id]) for instrument_id in expected)
        completed_cycles = min(leg_fill_counts, default=0)

        open_positions = [
            position
            for position in engine.cache.positions_open()
            if position.instrument_id.value in expected
        ]
        residual_exposure_ratio = 1.0 if open_positions else 0.0

        slippage_values: list[float] = []
        for order in engine.cache.orders():
            instrument_id = order.instrument_id.value
            if instrument_id not in expected:
                continue
            filled_qty = getattr(order, "filled_qty", None)
            avg_px = getattr(order, "avg_px", None)
            if filled_qty is None or avg_px is None:
                continue
            try:
                quantity = float(filled_qty.as_double())
                fill_price = float(avg_px)
                ts_fill = int(order.ts_last)
            except (AttributeError, TypeError, ValueError) as exc:
                raise RuntimeError("filled multi-leg order has invalid execution identity") from exc
            if quantity <= 0.0:
                continue
            reference = reference_close.get((instrument_id, ts_fill))
            if reference is None:
                raise RuntimeError(
                    "filled multi-leg order cannot be matched to its source BAR close"
                )
            slippage_values.append(abs(fill_price - reference) / reference * 10_000.0)

        if completed_cycles > 0 and not slippage_values:
            raise RuntimeError("completed multi-leg cycles have no measurable filled orders")
        slippage_bps = max(slippage_values, default=0.0)

        return MultiLegStressReport(
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            dataset_hash=dataset_hash,
            code_hash=code_hash,
            engine="nautilus_trader",
            engine_version=version("nautilus_trader"),
            expected_legs=len(expected),
            completed_cycles=completed_cycles,
            leg_fill_counts=leg_fill_counts,
            residual_exposure_ratio=residual_exposure_ratio,
            slippage_bps=slippage_bps,
        )
    finally:
        engine.dispose()
