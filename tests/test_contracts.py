from datetime import datetime, timezone
from math import inf, nan

import pytest

from mastertrd.contracts import EvaluationResult, MarketBar, MarketTick


def now() -> datetime:
    return datetime.now(timezone.utc)


def test_market_bar_accepts_consistent_ohlc():
    bar = MarketBar(now(), "BINANCE", "BTCUSDT", "1h", 100, 110, 90, 105, 12)
    assert bar.close == 105


def test_market_bar_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketBar(datetime.now(), "BINANCE", "BTCUSDT", "1h", 100, 110, 90, 105, 12)


def test_market_bar_rejects_missing_identity():
    with pytest.raises(ValueError, match="venue, instrument and timeframe"):
        MarketBar(now(), "", "BTCUSDT", "1h", 100, 110, 90, 105, 12)


def test_market_bar_rejects_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        MarketBar(now(), "BINANCE", "BTCUSDT", "1h", 100, inf, 90, 105, 12)


def test_market_bar_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume"):
        MarketBar(now(), "BINANCE", "BTCUSDT", "1h", 100, 110, 90, 105, -1)


def test_market_bar_rejects_inconsistent_high():
    with pytest.raises(ValueError, match="high"):
        MarketBar(now(), "BINANCE", "BTCUSDT", "1h", 100, 101, 90, 105, 12)


def test_market_bar_rejects_inconsistent_low():
    with pytest.raises(ValueError, match="low"):
        MarketBar(now(), "BINANCE", "BTCUSDT", "1h", 100, 110, 101, 105, 12)


def tick(**changes) -> MarketTick:
    values = dict(
        timestamp=now(),
        venue="BINANCE",
        instrument="BTCUSDT",
        bid=100.0,
        ask=100.2,
        bid_size=1.0,
        ask_size=2.0,
        last=100.1,
        last_size=0.5,
    )
    values.update(changes)
    return MarketTick(**values)


def test_market_tick_accepts_valid_book():
    result = tick()
    assert result.bid == 100.0
    assert result.ask == 100.2


def test_market_tick_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        tick(timestamp=datetime.now())


def test_market_tick_rejects_missing_identity():
    with pytest.raises(ValueError, match="venue and instrument"):
        tick(instrument="")


def test_market_tick_rejects_non_finite_values():
    with pytest.raises(ValueError, match="finite"):
        tick(ask_size=nan)


@pytest.mark.parametrize("field", ("bid", "ask"))
def test_market_tick_rejects_non_positive_quotes(field):
    with pytest.raises(ValueError, match="positive"):
        tick(**{field: 0.0})


@pytest.mark.parametrize("field", ("bid_size", "ask_size", "last_size"))
def test_market_tick_rejects_negative_sizes(field):
    with pytest.raises(ValueError, match="sizes"):
        tick(**{field: -0.1})


def test_market_tick_rejects_crossed_book():
    with pytest.raises(ValueError, match="crossed"):
        tick(bid=100.3, ask=100.2)


@pytest.mark.parametrize("last", (0.0, inf))
def test_market_tick_rejects_invalid_last_price(last):
    with pytest.raises(ValueError, match="last price"):
        tick(last=last)


def evaluation(**changes) -> EvaluationResult:
    values = dict(
        strategy_id="S-1",
        genome_hash="genome",
        dataset_hash="dataset",
        code_hash="code",
        engine="nautilus_trader",
        engine_version="1.231.0",
        total_return=0.10,
        sharpe=1.2,
        sortino=1.4,
        max_drawdown=0.05,
        profit_factor=1.3,
        expectancy=0.01,
        trade_count=10,
        turnover=2.0,
        fees=0.001,
        slippage=0.001,
        scores={"execution_backtest": 1.0},
    )
    values.update(changes)
    return EvaluationResult(**values)


def test_evaluation_result_accepts_finite_metrics():
    assert evaluation().trade_count == 10


def test_evaluation_result_rejects_missing_identity():
    with pytest.raises(ValueError, match="identity"):
        evaluation(code_hash="")


def test_evaluation_result_rejects_non_finite_metric_or_score():
    with pytest.raises(ValueError, match="finite"):
        evaluation(sharpe=nan)
    with pytest.raises(ValueError, match="finite"):
        evaluation(scores={"execution_backtest": inf})


@pytest.mark.parametrize(
    "changes",
    (
        {"trade_count": -1},
        {"fees": -0.01},
        {"slippage": -0.01},
    ),
)
def test_evaluation_result_rejects_negative_counts_and_costs(changes):
    with pytest.raises(ValueError, match="counts/costs"):
        evaluation(**changes)
