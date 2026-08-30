from datetime import datetime, timezone

import pytest

from mastertrd.contracts import MarketBar, StrategyState
from mastertrd.data.orderbook import OrderBookDataset, OrderBookEvent, OrderBookLevel, OrderBookTrade
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.hft_validation import HftLatencyProfile, validate_hft_candidate
from mastertrd.validation import ValidationEvidence


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="HFT-REAL-1",
        family="market_making",
        style="intraday",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="tick",
        entry={"kind": "two_sided_quote"},
        exit={"kind": "inventory_flatten"},
    )


def historical_l2(*, synthetic: bool = False) -> OrderBookDataset:
    events: list[OrderBookEvent] = []
    sequence = 1_000
    for cycle in range(8):
        base = 1_000_000 + cycle * 10_000_000
        events.extend(
            [
                OrderBookEvent(
                    sequence=sequence,
                    exchange_timestamp_ns=base,
                    local_timestamp_ns=base + 100_000,
                    bids=(OrderBookLevel(100.0, 2.0), OrderBookLevel(99.9, 3.0)),
                    asks=(OrderBookLevel(100.2, 2.0), OrderBookLevel(100.3, 3.0)),
                ),
                OrderBookEvent(
                    sequence=sequence + 1,
                    exchange_timestamp_ns=base + 3_000_000,
                    local_timestamp_ns=base + 3_100_000,
                    bids=(OrderBookLevel(100.0, 1.5), OrderBookLevel(99.9, 3.0)),
                    asks=(OrderBookLevel(100.2, 2.0), OrderBookLevel(100.3, 3.0)),
                    trades=(OrderBookTrade("SELL", 100.0, 5.0),),
                ),
                OrderBookEvent(
                    sequence=sequence + 2,
                    exchange_timestamp_ns=base + 6_000_000,
                    local_timestamp_ns=base + 6_100_000,
                    bids=(OrderBookLevel(100.0, 1.5), OrderBookLevel(99.9, 3.0)),
                    asks=(OrderBookLevel(100.2, 1.5), OrderBookLevel(100.3, 3.0)),
                    trades=(OrderBookTrade("BUY", 100.2, 5.0),),
                ),
            ]
        )
        sequence += 3
    return OrderBookDataset(
        venue="BINANCE",
        instrument="BTCUSDT",
        source_id="fixture:historical-l2",
        events=tuple(events),
        synthetic=synthetic,
    )


def latency() -> HftLatencyProfile:
    return HftLatencyProfile(feed_latency_ns=100_000, order_latency_ns=250_000)


def robust_base_evidence(genome: StrategyGenome) -> list[ValidationEvidence]:
    return [
        ValidationEvidence(
            strategy_id=genome.strategy_id,
            genome_hash=genome.genome_hash,
            evidence_type=evidence_type,
            dataset_hash="robust-dataset",
            code_hash="robust-code",
            engine="test",
            engine_version="1",
            passed=True,
        )
        for evidence_type in (
            "walk_forward",
            "cost_stress",
            "parameter_stability",
            "purged_cpcv",
            "monte_carlo",
            "asset_transfer",
        )
    ]


def test_real_l2_hft_evidence_is_bound_to_exact_dataset_and_unlocks_hft_robust_gate():
    genome = candidate()
    dataset = historical_l2()
    evidence = validate_hft_candidate(
        genome,
        dataset,
        latency_profile=latency(),
        queue_model="risk_adverse_queue_model",
    )

    assert evidence.evidence_type == "hft_real_l2"
    assert evidence.dataset_hash == dataset.dataset_hash
    assert evidence.engine == "hftbacktest"
    assert evidence.passed is True
    assert evidence.supporting_only is False
    assert evidence.metrics["completed_trades"] > 0

    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        genome,
        [*robust_base_evidence(genome), evidence],
    )
    assert decision.allowed is True
    assert not decision.missing_evidence


def test_synthetic_l2_validation_is_supporting_only_and_cannot_unlock_hft_promotion():
    genome = candidate()
    evidence = validate_hft_candidate(
        genome,
        historical_l2(synthetic=True),
        latency_profile=latency(),
        queue_model="risk_adverse_queue_model",
    )

    assert evidence.passed is True
    assert evidence.supporting_only is True

    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        genome,
        [*robust_base_evidence(genome), evidence],
    )
    assert decision.allowed is False
    assert decision.missing_evidence == frozenset({"hft_real_l2"})


def test_candle_only_dataset_fails_closed_for_hft_validation():
    bar = MarketBar(
        datetime.now(timezone.utc),
        "BINANCE",
        "BTCUSDT",
        "1m",
        100.0,
        101.0,
        99.0,
        100.5,
        10.0,
    )
    with pytest.raises(TypeError, match="OrderBookDataset"):
        validate_hft_candidate(
            candidate(),
            (bar,),
            latency_profile=latency(),
            queue_model="risk_adverse_queue_model",
        )
