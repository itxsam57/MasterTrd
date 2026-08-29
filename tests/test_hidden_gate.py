from dataclasses import replace

import pytest

from mastertrd.contracts import EvaluationResult, StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.hidden_gate import HiddenGatePolicy, hidden_test_evidence, regime_test_evidence
from mastertrd.holdout import chronological_holdout


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-hidden-trend",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def result(
    candidate: StrategyGenome,
    *,
    dataset_hash: str,
    total_return: float = 0.05,
    drawdown: float = 0.08,
    trades: int = 12,
) -> EvaluationResult:
    return EvaluationResult(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash=dataset_hash,
        code_hash="c" * 64,
        engine="nautilus_trader",
        engine_version="1.231.0",
        total_return=total_return,
        sharpe=0.8,
        sortino=1.0,
        max_drawdown=drawdown,
        profit_factor=1.2,
        expectancy=0.004,
        trade_count=trades,
        turnover=0.4,
        fees=0.002,
        slippage=0.002,
        scores={"execution_backtest": 1.0},
    )


def policy() -> HiddenGatePolicy:
    return HiddenGatePolicy(
        min_trades_per_evaluation=5,
        min_total_return=0.0,
        max_drawdown=0.20,
        min_regime_pass_ratio=0.75,
    )


def test_frozen_hidden_and_regime_records_allow_hidden_pass():
    candidate = genome()
    _, _, manifest = chronological_holdout(
        tuple(range(100)),
        hidden_fraction=0.20,
        dataset_hash="source-v1",
    )
    hidden_result = result(candidate, dataset_hash=manifest.manifest_hash)
    hidden = hidden_test_evidence(candidate, hidden_result, manifest, policy())

    regimes = [
        result(candidate, dataset_hash="1" * 64, total_return=0.04),
        result(candidate, dataset_hash="2" * 64, total_return=0.02),
        result(candidate, dataset_hash="3" * 64, total_return=0.01),
        result(candidate, dataset_hash="4" * 64, total_return=-0.01),
    ]
    regime = regime_test_evidence(candidate, regimes, policy())

    assert hidden.passed is True
    assert hidden.dataset_hash == manifest.manifest_hash
    assert regime.passed is True
    assert regime.metrics["passing_regime_ratio"] == 0.75

    decision = evaluate_validated_promotion(
        StrategyState.ROBUST,
        StrategyState.HIDDEN_PASS,
        candidate,
        [hidden, regime],
    )
    assert decision.allowed is True


def test_hidden_result_must_be_bound_to_exact_frozen_manifest():
    candidate = genome()
    _, _, manifest = chronological_holdout(tuple(range(20)), dataset_hash="source-v1")
    wrong = result(candidate, dataset_hash="x" * 64)
    with pytest.raises(ValueError, match="manifest_hash"):
        hidden_test_evidence(candidate, wrong, manifest, policy())


def test_weak_hidden_result_cannot_pass():
    candidate = genome()
    _, _, manifest = chronological_holdout(tuple(range(20)), dataset_hash="source-v1")
    weak = result(candidate, dataset_hash=manifest.manifest_hash, total_return=-0.02)
    evidence = hidden_test_evidence(candidate, weak, manifest, policy())
    assert evidence.passed is False


def test_regime_gate_rejects_mixed_identity_and_weak_coverage():
    candidate = genome()
    good = result(candidate, dataset_hash="1" * 64)
    mixed = replace(result(candidate, dataset_hash="2" * 64), code_hash="x" * 64)
    with pytest.raises(ValueError, match="code_hash"):
        regime_test_evidence(candidate, [good, mixed], policy())

    regimes = [
        good,
        result(candidate, dataset_hash="2" * 64, total_return=-0.01),
        result(candidate, dataset_hash="3" * 64, total_return=-0.02),
        result(candidate, dataset_hash="4" * 64, drawdown=0.25),
    ]
    evidence = regime_test_evidence(candidate, regimes, policy())
    assert evidence.passed is False
