from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar, StrategyState
from mastertrd.hidden_cycle import run_generated_hidden_cycle
from mastertrd.hidden_gate import HiddenGatePolicy
from mastertrd.holdout import chronological_holdout
from mastertrd.nautilus_data import market_bars_to_nautilus
from mastertrd.research.generator import generate_candidate


def _step(timeframe: str) -> timedelta:
    value = int(timeframe[:-1])
    return timedelta(minutes=value) if timeframe.endswith("m") else timedelta(hours=value)


def _cycle_closes(offset: float = 0.0):
    return (
        [2300.0 + offset - i * 2.0 for i in range(100)]
        + [2100.0 + offset + i * 4.0 for i in range(100)]
        + [2496.0 + offset - i * 5.0 for i in range(100)]
    )


def _bars(candidate, instrument, closes, *, start):
    step = _step(candidate.timeframe)
    market = []
    previous = closes[0] + 1.0
    for index, close in enumerate(closes):
        market.append(
            MarketBar(
                venue="BINANCE",
                instrument="ETHUSDT",
                timeframe=candidate.timeframe,
                timestamp=start + step * index,
                open=previous,
                high=max(previous, close) + 1.0,
                low=min(previous, close) - 1.0,
                close=close,
                volume=1.0,
            )
        )
        previous = close
    return market_bars_to_nautilus(market, instrument=instrument)


def test_generated_candidate_uses_frozen_hidden_tail_and_regime_reruns_for_hidden_pass():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    candidate = generate_candidate(family="trend", instruments=(instrument.id.value,), seed=42)
    start = datetime(2026, 2, 1, tzinfo=timezone.utc)
    closes = list(_cycle_closes()) * 5
    all_bars = _bars(candidate, instrument, closes, start=start)
    _, hidden, manifest = chronological_holdout(
        all_bars,
        hidden_fraction=0.20,
        min_research=600,
        min_hidden=300,
        dataset_hash="frozen-source-v1",
    )
    step = _step(candidate.timeframe)
    regime_start = start + step * 2000
    regimes = [
        ("regime-trend-a", _bars(candidate, instrument, _cycle_closes(0.0), start=regime_start)),
        ("regime-trend-b", _bars(candidate, instrument, _cycle_closes(30.0), start=regime_start + step * 400)),
        ("regime-trend-c", _bars(candidate, instrument, _cycle_closes(-30.0), start=regime_start + step * 800)),
        ("regime-trend-d", _bars(candidate, instrument, _cycle_closes(60.0), start=regime_start + step * 1200)),
    ]
    policy = HiddenGatePolicy(
        min_trades_per_evaluation=1,
        min_total_return=-0.10,
        max_drawdown=0.50,
        min_regime_pass_ratio=0.75,
    )

    cycle = run_generated_hidden_cycle(
        candidate=candidate,
        instrument=instrument,
        hidden_data=hidden,
        manifest=manifest,
        regime_datasets=regimes,
        code_hash="hidden-code-v1",
        trade_size="0.01000",
        policy=policy,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert cycle.hidden_result.dataset_hash == manifest.manifest_hash
    assert len(cycle.regime_results) == 4
    assert {record.evidence_type for record in cycle.evidence} == {"hidden_test", "regime_test"}
    assert all(record.passed for record in cycle.evidence)
    assert cycle.promotion.allowed is True
    assert cycle.promotion.target is StrategyState.HIDDEN_PASS
    assert all("hidden" not in key.lower() or key == "hidden_observation_count" for key in cycle.evidence[0].metrics)
