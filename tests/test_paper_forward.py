from dataclasses import replace

import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.paper_forward import (
    PaperForwardReport,
    PaperMinimumPolicy,
    paper_minimum_evidence,
)


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-forward-trend",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def report(
    candidate: StrategyGenome,
    session_id: str,
    *,
    duration: int = 3600,
    trades: int = 6,
    total_return: float = 0.02,
    drawdown: float = 0.05,
    reconciliation_errors: int = 0,
) -> PaperForwardReport:
    return PaperForwardReport(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        session_id=session_id,
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        duration_seconds=duration,
        closed_trades=trades,
        total_return=total_return,
        max_drawdown=drawdown,
        reconciliation_errors=reconciliation_errors,
        completed=True,
    )


def policy() -> PaperMinimumPolicy:
    return PaperMinimumPolicy(
        min_sessions=2,
        min_duration_seconds=7200,
        min_closed_trades=10,
        min_total_return=0.0,
        max_drawdown=0.20,
    )


def test_multiple_real_forward_sessions_allow_challenger_promotion():
    candidate = genome()
    evidence = paper_minimum_evidence(
        candidate,
        [report(candidate, "session-1"), report(candidate, "session-2")],
        policy(),
    )

    assert evidence.evidence_type == "paper_minimum_evidence"
    assert evidence.passed is True
    assert evidence.metrics["session_count"] == 2.0
    assert evidence.metrics["closed_trades"] == 12.0
    assert evidence.metrics["duration_seconds"] == 7200.0

    decision = evaluate_validated_promotion(
        StrategyState.PAPER,
        StrategyState.CHALLENGER,
        candidate,
        [evidence],
    )
    assert decision.allowed is True


def test_duplicate_sessions_cannot_inflate_forward_evidence():
    candidate = genome()
    first = report(candidate, "session-1")
    with pytest.raises(ValueError, match="unique"):
        paper_minimum_evidence(candidate, [first, first], policy())


def test_reconciliation_error_or_weak_performance_blocks_challenger():
    candidate = genome()
    bad_reconciliation = [
        report(candidate, "session-1"),
        report(candidate, "session-2", reconciliation_errors=1),
    ]
    assert paper_minimum_evidence(candidate, bad_reconciliation, policy()).passed is False

    weak = [
        report(candidate, "session-1", total_return=-0.10),
        report(candidate, "session-2", total_return=-0.10, drawdown=0.25),
    ]
    assert paper_minimum_evidence(candidate, weak, policy()).passed is False


def test_mixed_candidate_or_engine_identity_is_rejected():
    candidate = genome()
    first = report(candidate, "session-1")
    with pytest.raises(ValueError, match="strategy_id"):
        paper_minimum_evidence(
            candidate,
            [first, replace(report(candidate, "session-2"), strategy_id="other")],
            policy(),
        )
    with pytest.raises(ValueError, match="engine"):
        paper_minimum_evidence(
            candidate,
            [first, replace(report(candidate, "session-2"), engine="other")],
            policy(),
        )


def test_policy_and_report_reject_impossible_values():
    with pytest.raises(ValueError):
        PaperMinimumPolicy(0, 1, 1, 0.0, 0.2)
    candidate = genome()
    with pytest.raises(ValueError):
        replace(report(candidate, "session-1"), duration_seconds=-1)
