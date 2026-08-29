from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.validation import ValidationEvidence, validated_evidence_types
from mastertrd.governor import evaluate_validated_promotion


def genome(family: str = "trend") -> StrategyGenome:
    return StrategyGenome(
        strategy_id="candidate-1",
        family=family,
        style="day",
        instruments=("BTCUSDT",),
        timeframe="5m",
        entry={"kind": "breakout", "window": 20},
        exit={"kind": "atr", "multiple": 2.0},
        allow_short=True,
    )


def evidence(g: StrategyGenome, kind: str, *, passed: bool = True) -> ValidationEvidence:
    return ValidationEvidence(
        strategy_id=g.strategy_id,
        genome_hash=g.genome_hash,
        evidence_type=kind,
        dataset_hash="dataset-sha256",
        code_hash="code-sha256",
        engine="mastertrd-test",
        engine_version="1",
        passed=passed,
        metrics={"score": 1.0, "drawdown": -0.05},
    )


def generic_robust_records(g: StrategyGenome) -> list[ValidationEvidence]:
    return [
        evidence(g, "walk_forward"),
        evidence(g, "cost_stress"),
        evidence(g, "parameter_stability"),
        evidence(g, "purged_cpcv"),
        evidence(g, "monte_carlo"),
        evidence(g, "asset_transfer"),
    ]


def test_evidence_hash_is_deterministic_across_metric_order():
    g = genome()
    a = evidence(g, "walk_forward")
    b = ValidationEvidence(
        strategy_id=g.strategy_id,
        genome_hash=g.genome_hash,
        evidence_type="walk_forward",
        dataset_hash="dataset-sha256",
        code_hash="code-sha256",
        engine="mastertrd-test",
        engine_version="1",
        passed=True,
        metrics={"drawdown": -0.05, "score": 1.0},
    )
    assert a.evidence_hash == b.evidence_hash


def test_failed_or_wrong_genome_evidence_is_not_accepted():
    g = genome()
    good = evidence(g, "walk_forward")
    failed = evidence(g, "cost_stress", passed=False)
    wrong = ValidationEvidence(
        strategy_id=g.strategy_id,
        genome_hash="other-genome",
        evidence_type="parameter_stability",
        dataset_hash="dataset-sha256",
        code_hash="code-sha256",
        engine="mastertrd-test",
        engine_version="1",
        passed=True,
        metrics={"score": 1.0},
    )
    assert validated_evidence_types(g, [good, failed, wrong]) == {"walk_forward"}


def test_trend_strategy_requires_real_robustness_records_for_promotion():
    g = genome("trend")
    decision = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        g,
        generic_robust_records(g),
    )
    assert decision.allowed


def test_hft_strategy_cannot_become_robust_without_hft_specialist_evidence():
    g = genome("scalping")
    generic = generic_robust_records(g)
    denied = evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        g,
        generic,
    )
    assert not denied.allowed
    assert denied.missing_evidence == {
        "hft_queue_model",
        "hft_feed_latency_stress",
        "hft_order_latency_stress",
        "spread_stress",
    }

    complete = generic + [
        evidence(g, "hft_queue_model"),
        evidence(g, "hft_feed_latency_stress"),
        evidence(g, "hft_order_latency_stress"),
        evidence(g, "spread_stress"),
    ]
    assert evaluate_validated_promotion(
        StrategyState.BACKTESTED,
        StrategyState.ROBUST,
        g,
        complete,
    ).allowed


def test_hidden_gate_requires_hidden_and_regime_evidence():
    g = genome()
    denied = evaluate_validated_promotion(
        StrategyState.ROBUST,
        StrategyState.HIDDEN_PASS,
        g,
        [evidence(g, "hidden_test")],
    )
    assert not denied.allowed
    assert denied.missing_evidence == {"regime_test"}
