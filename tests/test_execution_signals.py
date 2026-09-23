from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar
from mastertrd.execution_signals import SignalDirection, evaluate_bar_signal, evaluate_multileg_signal
from mastertrd.genome import StrategyGenome


def _bars(closes: list[float], *, instrument: str = "ETHUSDT.BINANCE") -> tuple[MarketBar, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output = []
    for index, close in enumerate(closes):
        output.append(
            MarketBar(
                timestamp=start + timedelta(minutes=index),
                venue="BINANCE",
                instrument=instrument,
                timeframe="1m",
                open=close,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=100.0 + index,
            )
        )
    return tuple(output)


def _genome(family: str, entry: dict, *, instruments=("ETHUSDT.BINANCE",)) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=f"test-{family}",
        family=family,
        style=family,
        instruments=tuple(instruments),
        timeframe="1m",
        entry=entry,
        exit={"type": "test"},
        allow_short=True,
    )


def test_ema_cross_signal_turns_long_on_rising_market() -> None:
    genome = _genome("trend", {"type": "ema_cross", "fast": 2, "slow": 5})
    decision = evaluate_bar_signal(genome, _bars([10, 10, 10, 11, 12, 14, 17]))
    assert decision.direction is SignalDirection.LONG


def test_rsi_momentum_turns_long_above_threshold() -> None:
    genome = _genome("momentum", {"type": "rsi_momentum", "period": 3, "threshold": 55})
    decision = evaluate_bar_signal(genome, _bars([10, 10.5, 11, 12, 13, 14]))
    assert decision.direction is SignalDirection.LONG


def test_donchian_breakout_uses_prior_window_not_current_high() -> None:
    genome = _genome("breakout", {"type": "donchian_breakout", "window": 3})
    decision = evaluate_bar_signal(genome, _bars([10, 10.2, 10.4, 12.0]))
    assert decision.direction is SignalDirection.LONG


def test_zscore_reversion_buys_negative_extreme() -> None:
    genome = _genome("mean_reversion", {"type": "zscore_reversion", "window": 4, "z": 1.0})
    decision = evaluate_bar_signal(genome, _bars([10, 10, 10, 10, 6]))
    assert decision.direction is SignalDirection.LONG


def test_stat_arb_multileg_signal_responds_to_spread_extreme() -> None:
    instruments = ("ETHUSDT.BINANCE", "BTCUSDT.BINANCE")
    genome = _genome(
        "stat_arb",
        {"type": "cointegration_spread", "window": 4, "z_entry": 1.0},
        instruments=instruments,
    )
    decision = evaluate_multileg_signal(
        genome,
        {
            instruments[0]: _bars([100, 100, 100, 100, 120], instrument=instruments[0]),
            instruments[1]: _bars([100, 100, 100, 100, 100], instrument=instruments[1]),
        },
    )
    assert decision.direction is SignalDirection.SHORT


def test_hedged_basis_signal_preserves_configured_hedge_ratio() -> None:
    instruments = ("ETHUSDT.BINANCE", "BTCUSDT.BINANCE")
    ratio = 1.25
    genome = _genome(
        "delta_neutral",
        {"type": "hedged_basis", "hedge_ratio": ratio},
        instruments=instruments,
    )
    decision = evaluate_multileg_signal(
        genome,
        {
            instruments[0]: _bars([150.0], instrument=instruments[0]),
            instruments[1]: _bars([100.0], instrument=instruments[1]),
        },
    )

    assert decision.direction is SignalDirection.SHORT
    assert decision.legs[instruments[0]] == -1.0
    assert decision.legs[instruments[1]] == ratio


def test_macd_trend_turns_long_on_accelerating_market() -> None:
    genome = _genome("trend", {"type": "macd_trend", "fast": 3, "slow": 6, "signal": 3})
    decision = evaluate_bar_signal(genome, _bars([10, 10, 10, 10.5, 11, 12, 14, 17, 21, 26]))
    assert decision.direction is SignalDirection.LONG


def test_bollinger_reversion_buys_lower_band_extreme() -> None:
    genome = _genome(
        "mean_reversion",
        {"type": "bollinger_reversion", "window": 5, "deviations": 1.5},
    )
    decision = evaluate_bar_signal(genome, _bars([10, 10.2, 9.8, 10.1, 9.9, 6.0]))
    assert decision.direction is SignalDirection.LONG


def test_rsi_reversion_buys_oversold_market() -> None:
    genome = _genome(
        "mean_reversion",
        {"type": "rsi_reversion", "period": 2, "lower": 20, "upper": 80, "window": 5},
    )
    decision = evaluate_bar_signal(genome, _bars([12, 11, 10, 9, 8, 7]))
    assert decision.direction is SignalDirection.LONG


def test_absolute_momentum_turns_long_after_large_positive_move() -> None:
    genome = _genome(
        "momentum",
        {"type": "absolute_momentum", "lookback": 4, "threshold": 0.05},
    )
    decision = evaluate_bar_signal(genome, _bars([10, 10.2, 10.4, 10.8, 11.5]))
    assert decision.direction is SignalDirection.LONG


def test_bollinger_squeeze_breakout_requires_squeeze_and_breakout() -> None:
    genome = _genome(
        "breakout",
        {
            "type": "bollinger_squeeze_breakout",
            "window": 5,
            "deviations": 1.5,
            "squeeze_width": 0.08,
        },
    )
    decision = evaluate_bar_signal(genome, _bars([10, 10.05, 9.95, 10.02, 9.98, 10.5]))
    assert decision.direction is SignalDirection.LONG
