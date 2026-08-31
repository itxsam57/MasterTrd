from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.risk_profiles import build_research_backtest_risk_runtime


def _bars(instrument: str, closes: list[float]) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        MarketBar(
            timestamp=start + timedelta(hours=index),
            venue="BINANCE",
            instrument=instrument,
            timeframe="1h",
            open=close,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=100.0,
        )
        for index, close in enumerate(closes)
    ]


def test_nautilus_multileg_strategy_evaluates_shared_spread_exit_policy() -> None:
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    eth = TestInstrumentProvider.ethusdt_binance()
    btc = TestInstrumentProvider.btcusdt_binance()
    genome = StrategyGenome(
        strategy_id="stat-arb-exit-live-path",
        family="stat_arb",
        style="stat_arb",
        instruments=(eth.id.value, btc.id.value),
        timeframe="1h",
        entry={"type": "cointegration_spread", "window": 3, "z_entry": 1.5},
        exit={"type": "spread_mean_exit", "z_exit": 0.5},
        allow_short=True,
    )
    strategy = compile_genome_to_nautilus(
        genome,
        instrument=eth,
        instrument_map={eth.id.value: eth, btc.id.value: btc},
        trade_size_override="0.10",
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    strategy._bars[eth.id.value] = _bars(eth.id.value, [109.0, 110.0, 111.0, 110.0])
    strategy._bars[btc.id.value] = _bars(btc.id.value, [100.0, 100.0, 100.0, 100.0])
    strategy._last_legs = {eth.id.value: -1.0, btc.id.value: 1.0}
    strategy._bars_held = 4

    decision = strategy._evaluate_policy()

    assert decision.direction is SignalDirection.FLAT
    assert decision.close_position is True
    assert decision.reason == "spread_mean_exit"
    assert decision.legs == {eth.id.value: 0.0, btc.id.value: 0.0}
