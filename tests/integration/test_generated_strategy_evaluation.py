from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar
from mastertrd.nautilus_data import market_bars_to_nautilus
from mastertrd.nautilus_evaluation import run_binance_spot_evaluation
from mastertrd.research.generator import generate_candidate


def _step(timeframe: str) -> timedelta:
    value = int(timeframe[:-1])
    unit = timeframe[-1]
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    raise AssertionError(f"unexpected trend timeframe {timeframe}")


def test_generated_candidate_reaches_real_nautilus_evaluation():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = generate_candidate(
        family="trend",
        instruments=(instrument.id.value,),
        seed=42,
    )
    step = _step(candidate.timeframe)
    closes = (
        [2300.0 - i * 2.0 for i in range(100)]
        + [2100.0 + i * 4.0 for i in range(100)]
        + [2496.0 - i * 5.0 for i in range(100)]
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    market_bars = []
    previous = closes[0] + 1.0
    for index, close in enumerate(closes):
        open_value = previous
        market_bars.append(
            MarketBar(
                venue="BINANCE",
                instrument="ETHUSDT",
                timeframe=candidate.timeframe,
                timestamp=start + step * index,
                open=open_value,
                high=max(open_value, close) + 1.0,
                low=min(open_value, close) - 1.0,
                close=close,
                volume=1.0,
            )
        )
        previous = close

    bars = market_bars_to_nautilus(market_bars, instrument=instrument)
    result = run_binance_spot_evaluation(
        genome=candidate,
        instrument=instrument,
        data=bars,
        dataset_hash="generated-trend-dataset-v1",
        code_hash="generated-trend-code-v1",
        trade_size_override="0.01000",
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert result.strategy_id == candidate.strategy_id
    assert result.genome_hash == candidate.genome_hash
    assert result.engine == "nautilus_trader"
    assert result.trade_count >= 1
    assert result.scores["execution_backtest"] == 1.0
