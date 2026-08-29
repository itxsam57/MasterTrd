from math import isfinite

from mastertrd.genome import StrategyGenome
from mastertrd.hft_engine import run_hftbacktest_stress_suite
from mastertrd.hft_validation import HftStressPolicy, hft_stress_evidence


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="HFT-engine-1",
        family="market_making",
        style="intraday",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="tick",
        entry={"kind": "two_sided_quote"},
        exit={"kind": "inventory_flatten"},
    )


def test_real_hftbacktest_stress_suite_produces_trade_derived_report():
    genome = candidate()
    report = run_hftbacktest_stress_suite(
        genome,
        dataset_hash="synthetic-l2-stress-v1",
        code_hash="integration-code-v1",
        cycles=30,
    )

    assert report.strategy_id == genome.strategy_id
    assert report.genome_hash == genome.genome_hash
    assert report.dataset_hash == "synthetic-l2-stress-v1"
    assert report.code_hash == "integration-code-v1"
    assert report.engine_version
    assert report.queue_model == "risk_adverse_queue_model"
    assert report.completed_trades >= 20
    assert all(
        isfinite(value)
        for value in (
            report.baseline_return,
            report.queue_model_return,
            report.feed_latency_stress_return,
            report.order_latency_stress_return,
            report.spread_stress_return,
        )
    )

    records = hft_stress_evidence(
        genome,
        report,
        HftStressPolicy(
            min_completed_trades=20,
            min_stressed_return=-1.0,
            max_queue_degradation=1.0,
            max_feed_latency_degradation=1.0,
            max_order_latency_degradation=1.0,
            max_spread_degradation=1.0,
        ),
    )
    assert len(records) == 4
    assert all(record.engine == "hftbacktest" for record in records)
