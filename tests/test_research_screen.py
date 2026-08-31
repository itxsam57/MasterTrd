from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar
from mastertrd.research.generator import generate_candidate
from mastertrd.research.screen import screen_genome


def _bars(instrument: str, count: int = 180) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars: list[MarketBar] = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.35 + (2.0 if index % 11 == 0 else 0.0)
        bars.append(
            MarketBar(
                venue="BINANCE",
                instrument=instrument,
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * index),
                open=previous,
                high=max(previous, close) + 0.5,
                low=min(previous, close) - 0.5,
                close=close,
                volume=1000.0 + index,
            )
        )
        previous = close
    return bars


def test_screen_result_keeps_original_genome_hash_and_uses_shared_signals():
    genome = generate_candidate(family="momentum", instruments=("ETHUSDT",), seed=42)
    bars = _bars("ETHUSDT")

    result = screen_genome(
        genome,
        {genome.instruments[0]: bars},
        fees=0.001,
        slippage=0.0005,
    )

    assert result.genome_hash == genome.genome_hash
    assert result.engine == "vectorbt"
    assert result.dataset_hash
    assert result.code_hash
    assert result.trade_count >= 0
    assert result.fees == 0.001
    assert result.slippage == 0.0005


def test_screen_genome_rejects_missing_instrument_data():
    genome = generate_candidate(family="breakout", instruments=("ETHUSDT",), seed=7)

    try:
        screen_genome(genome, {}, fees=0.0, slippage=0.0)
    except ValueError as exc:
        assert "instrument" in str(exc).lower()
    else:
        raise AssertionError("missing instrument data must fail closed")
