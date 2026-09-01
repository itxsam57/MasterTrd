from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

import mastertrd.research.screen as screen
from mastertrd.contracts import MarketBar
from mastertrd.execution_policy import PositionState, evaluate_execution_policy
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome


def _bars(count: int = 240) -> tuple[MarketBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    values: list[MarketBar] = []
    previous = 100.0
    for index in range(count):
        cycle = (index % 32) - 16
        close = 100.0 + index * 0.025 + cycle * 0.22 + (2.5 if index % 47 == 0 else 0.0)
        values.append(
            MarketBar(
                timestamp=start + timedelta(minutes=5 * index),
                venue="BINANCE",
                instrument="BTCUSDT.BINANCE",
                timeframe="5m",
                open=previous,
                high=max(previous, close) + 0.8,
                low=min(previous, close) - 0.7,
                close=close,
                volume=1000.0 + index,
            )
        )
        previous = close
    return tuple(values)


def _genomes() -> tuple[StrategyGenome, ...]:
    instrument = "BTCUSDT.BINANCE"
    shared = {
        "instruments": (instrument,),
        "timeframe": "5m",
        "data_requirements": ("BAR",),
        "allow_short": True,
    }
    return (
        StrategyGenome(
            strategy_id="PARITY-TREND",
            family="trend",
            style="trend",
            entry={"type": "ema_cross", "fast": 5, "slow": 20},
            exit={"type": "cross_reverse"},
            **shared,
        ),
        StrategyGenome(
            strategy_id="PARITY-MOMENTUM",
            family="momentum",
            style="momentum",
            entry={"type": "rsi_momentum", "period": 7, "threshold": 58},
            exit={"type": "atr_bracket", "stop_atr": 2.0, "target_atr": 2.5, "atr_period": 7},
            **shared,
        ),
        StrategyGenome(
            strategy_id="PARITY-BREAKOUT",
            family="breakout",
            style="breakout",
            entry={"type": "donchian_breakout", "window": 18},
            exit={"type": "atr_bracket", "stop_atr": 2.0, "target_atr": 2.5, "atr_period": 7},
            **shared,
        ),
        StrategyGenome(
            strategy_id="PARITY-MEAN",
            family="mean_reversion",
            style="mean_reversion",
            entry={"type": "zscore_reversion", "window": 18, "z": 1.25},
            exit={"type": "mean_or_atr_stop", "stop_atr": 2.0, "atr_period": 7},
            **shared,
        ),
        StrategyGenome(
            strategy_id="PARITY-VOL",
            family="volatility",
            style="volatility",
            entry={"type": "volatility_breakout", "lookback": 10, "multiplier": 1.1},
            exit={"type": "atr_bracket", "stop_atr": 2.0, "target_atr": 2.5, "atr_period": 7},
            **shared,
        ),
    )


def _reference_prefix_signals(
    genome: StrategyGenome,
    bars: tuple[MarketBar, ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    count = len(bars)
    entries = np.zeros(count, dtype=bool)
    exits = np.zeros(count, dtype=bool)
    short_entries = np.zeros(count, dtype=bool)
    short_exits = np.zeros(count, dtype=bool)
    position = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)

    for index, current in enumerate(bars):
        if position.direction is not SignalDirection.FLAT:
            position = PositionState(
                direction=position.direction,
                entry_price=position.entry_price,
                peak_price=max(position.peak_price, float(current.high)),
                trough_price=min(position.trough_price, float(current.low)),
                bars_held=position.bars_held + 1,
            )
        decision = evaluate_execution_policy(genome, bars[: index + 1], position)

        if position.direction is SignalDirection.FLAT:
            if decision.direction is SignalDirection.LONG:
                entries[index] = True
                price = float(current.close)
                position = PositionState(SignalDirection.LONG, price, price, price, 0)
            elif decision.direction is SignalDirection.SHORT and genome.allow_short:
                short_entries[index] = True
                price = float(current.close)
                position = PositionState(SignalDirection.SHORT, price, price, price, 0)
            continue

        if not decision.close_position:
            continue

        if position.direction is SignalDirection.LONG:
            exits[index] = True
        else:
            short_exits[index] = True

        if decision.direction is SignalDirection.LONG:
            entries[index] = True
            price = float(current.close)
            position = PositionState(SignalDirection.LONG, price, price, price, 0)
        elif decision.direction is SignalDirection.SHORT and genome.allow_short:
            short_entries[index] = True
            price = float(current.close)
            position = PositionState(SignalDirection.SHORT, price, price, price, 0)
        else:
            position = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)

    return entries, exits, short_entries, short_exits


@pytest.mark.parametrize("genome", _genomes(), ids=lambda genome: genome.family)
def test_fast_single_leg_screen_matches_authoritative_prefix_policy(genome: StrategyGenome) -> None:
    bars = _bars()
    expected = _reference_prefix_signals(genome, bars)
    actual = screen._single_leg_signals(genome, bars)

    for expected_signal, actual_signal in zip(expected, actual, strict=True):
        assert np.array_equal(actual_signal, expected_signal)


def test_single_leg_screen_does_not_replay_growing_history_for_every_bar(monkeypatch) -> None:
    bars = _bars(320)
    genome = _genomes()[1]
    observed_history_items = 0
    original = screen.evaluate_execution_policy

    def counted_policy(candidate, history, position):
        nonlocal observed_history_items
        observed_history_items += len(history)
        return original(candidate, history, position)

    monkeypatch.setattr(screen, "evaluate_execution_policy", counted_policy)
    screen._single_leg_signals(genome, bars)

    # A linear screening path may inspect a small bounded amount of history per
    # bar, but it must never replay 1 + 2 + ... + N prefixes. Keep this bound
    # deliberately loose so it measures algorithmic shape, not machine speed.
    assert observed_history_items <= len(bars) * 8
