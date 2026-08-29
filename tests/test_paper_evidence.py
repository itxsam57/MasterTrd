import pytest

from mastertrd.contracts import StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.paper_evidence import PaperStartReceipt, paper_started_evidence


def genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-paper-trend",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def receipt(candidate: StrategyGenome, *, connected: bool = True) -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        session_id="paper-session-001",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=connected,
    )


def test_real_nautilus_sandbox_receipt_allows_paper_entry():
    candidate = genome()
    evidence = paper_started_evidence(candidate, receipt(candidate))

    assert evidence.evidence_type == "paper_started"
    assert evidence.passed is True
    assert evidence.engine == "nautilus_trader"
    assert evidence.metrics["sandbox_connected"] == 1.0

    decision = evaluate_validated_promotion(
        StrategyState.HIDDEN_PASS,
        StrategyState.PAPER,
        candidate,
        [evidence],
    )
    assert decision.allowed is True


def test_disconnected_or_wrong_identity_cannot_start_paper():
    candidate = genome()
    disconnected = paper_started_evidence(candidate, receipt(candidate, connected=False))
    assert disconnected.passed is False

    wrong = receipt(candidate)
    wrong = PaperStartReceipt(
        strategy_id="other",
        genome_hash=wrong.genome_hash,
        session_id=wrong.session_id,
        venue=wrong.venue,
        engine=wrong.engine,
        engine_version=wrong.engine_version,
        connected=True,
    )
    with pytest.raises(ValueError, match="strategy_id"):
        paper_started_evidence(candidate, wrong)


def test_non_nautilus_receipt_cannot_start_paper():
    candidate = genome()
    base = receipt(candidate)
    other = PaperStartReceipt(
        strategy_id=base.strategy_id,
        genome_hash=base.genome_hash,
        session_id=base.session_id,
        venue=base.venue,
        engine="other_engine",
        engine_version="1",
        connected=True,
    )
    evidence = paper_started_evidence(candidate, other)
    assert evidence.passed is False
