import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.hft_validation import HftStressPolicy, HftStressReport, hft_stress_evidence


def candidate() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="HFT-1",
        family="market_making",
        style="intraday",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="tick",
        entry={"kind": "two_sided_quote"},
        exit={"kind": "inventory_flatten"},
    )


def report(**changes) -> HftStressReport:
    values = dict(
        strategy_id="HFT-1",
        genome_hash=candidate().genome_hash,
        dataset_hash="l2-btcusdt-001",
        code_hash="code-001",
        engine_version="2.4.2",
        queue_model="risk_adverse_queue_model",
        baseline_return=0.10,
        queue_model_return=0.08,
        feed_latency_stress_return=0.07,
        order_latency_stress_return=0.065,
        spread_stress_return=0.06,
        completed_trades=120,
    )
    values.update(changes)
    return HftStressReport(**values)


def policy() -> HftStressPolicy:
    return HftStressPolicy(
        min_completed_trades=50,
        min_stressed_return=0.0,
        max_queue_degradation=0.40,
        max_feed_latency_degradation=0.40,
        max_order_latency_degradation=0.45,
        max_spread_degradation=0.50,
    )


def test_hft_report_produces_supporting_specialist_evidence_only():
    genome = candidate()
    records = hft_stress_evidence(genome, report(), policy())

    assert {record.evidence_type for record in records} == {
        "hft_queue_model",
        "hft_feed_latency_stress",
        "hft_order_latency_stress",
        "spread_stress",
    }
    assert all(record.passed for record in records)
    assert all(record.engine == "hftbacktest" for record in records)
    assert all(record.supporting_only for record in records)

    # Generic ROBUST prerequisites are evaluated before family-specific evidence.
    # The dedicated real-L2 integration test proves hft_real_l2 remains required
    # once those generic prerequisites are satisfied.
    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        genome,
        records,
    )
    assert decision.allowed is False
    assert decision.missing_evidence == frozenset({
        "walk_forward",
        "cost_stress",
        "parameter_stability",
        "purged_cpcv",
        "monte_carlo",
        "asset_transfer",
    })


def test_hft_stress_failure_blocks_its_specialist_record():
    records = hft_stress_evidence(
        candidate(),
        report(feed_latency_stress_return=0.01),
        policy(),
    )
    by_type = {record.evidence_type: record for record in records}
    assert by_type["hft_feed_latency_stress"].passed is False
    assert by_type["hft_queue_model"].passed is True
    assert all(record.supporting_only for record in records)


def test_hft_report_is_bound_to_candidate_and_hft_engine_identity():
    genome = candidate()
    with pytest.raises(ValueError, match="strategy_id"):
        hft_stress_evidence(genome, report(strategy_id="OTHER"), policy())
    with pytest.raises(ValueError, match="genome_hash"):
        hft_stress_evidence(genome, report(genome_hash="wrong"), policy())
    with pytest.raises(ValueError, match="queue_model"):
        hft_stress_evidence(genome, report(queue_model=""), policy())


def test_hft_policy_rejects_impossible_thresholds():
    with pytest.raises(ValueError):
        HftStressPolicy(0, 0.0, 0.4, 0.4, 0.45, 0.5)
    with pytest.raises(ValueError):
        HftStressPolicy(50, 0.0, 1.1, 0.4, 0.45, 0.5)
