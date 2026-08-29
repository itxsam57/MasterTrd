import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.champion import ChampionComparisonPolicy, champion_comparison_evidence
from mastertrd.validation import ValidationEvidence


def genome(strategy_id: str) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=strategy_id,
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def paper(candidate: StrategyGenome, *, total_return: float, drawdown: float, trades: float = 20.0, passed: bool = True) -> ValidationEvidence:
    return ValidationEvidence(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        evidence_type="paper_minimum_evidence",
        dataset_hash=f"paper-{candidate.strategy_id}",
        code_hash=candidate.genome_hash,
        engine="nautilus_trader",
        engine_version="1.231.0",
        passed=passed,
        metrics={
            "session_count": 2.0,
            "duration_seconds": 7200.0,
            "closed_trades": trades,
            "total_return": total_return,
            "max_drawdown": drawdown,
            "reconciliation_errors": 0.0,
            "completed_sessions": 2.0,
        },
    )


def policy() -> ChampionComparisonPolicy:
    return ChampionComparisonPolicy(
        min_closed_trades=10,
        min_score_improvement=0.02,
        max_drawdown_ratio=1.25,
    )


def test_first_qualified_challenger_can_become_champion():
    candidate = genome("S-first")
    evidence = champion_comparison_evidence(
        candidate,
        paper(candidate, total_return=0.08, drawdown=0.05),
        None,
        policy(),
    )
    assert evidence.evidence_type == "champion_comparison"
    assert evidence.passed is True
    assert evidence.metrics["incumbent_present"] == 0.0

    decision = evaluate_validated_promotion(
        StrategyState.CHALLENGER,
        StrategyState.CHAMPION,
        candidate,
        [evidence],
    )
    assert decision.allowed is True


def test_challenger_must_beat_incumbent_by_required_risk_adjusted_margin():
    candidate = genome("S-challenger")
    incumbent = genome("S-incumbent")

    winning = champion_comparison_evidence(
        candidate,
        paper(candidate, total_return=0.12, drawdown=0.05),
        paper(incumbent, total_return=0.07, drawdown=0.05),
        policy(),
    )
    assert winning.passed is True
    assert winning.metrics["score_improvement"] >= 0.02

    losing = champion_comparison_evidence(
        candidate,
        paper(candidate, total_return=0.071, drawdown=0.05),
        paper(incumbent, total_return=0.07, drawdown=0.05),
        policy(),
    )
    assert losing.passed is False


def test_excess_drawdown_blocks_champion_even_when_return_is_higher():
    candidate = genome("S-risky")
    incumbent = genome("S-incumbent")
    evidence = champion_comparison_evidence(
        candidate,
        paper(candidate, total_return=0.30, drawdown=0.20),
        paper(incumbent, total_return=0.08, drawdown=0.05),
        policy(),
    )
    assert evidence.passed is False


def test_failed_or_wrong_identity_paper_evidence_is_rejected():
    candidate = genome("S-candidate")
    incumbent = genome("S-incumbent")
    assert champion_comparison_evidence(
        candidate,
        paper(candidate, total_return=0.10, drawdown=0.05, passed=False),
        paper(incumbent, total_return=0.06, drawdown=0.05),
        policy(),
    ).passed is False

    with pytest.raises(ValueError, match="strategy_id"):
        champion_comparison_evidence(
            candidate,
            paper(incumbent, total_return=0.10, drawdown=0.05),
            None,
            policy(),
        )


def test_policy_rejects_impossible_values():
    with pytest.raises(ValueError):
        ChampionComparisonPolicy(0, 0.02, 1.25)
    with pytest.raises(ValueError):
        ChampionComparisonPolicy(10, -0.01, 1.25)
    with pytest.raises(ValueError):
        ChampionComparisonPolicy(10, 0.02, 0.0)
