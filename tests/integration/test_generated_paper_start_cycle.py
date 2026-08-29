from mastertrd.contracts import StrategyState
from mastertrd.paper_cycle import start_generated_paper_cycle
from mastertrd.research.generator import generate_candidate


def test_hidden_pass_candidate_requires_real_nautilus_sandbox_receipt_for_paper_admission():
    candidate = generate_candidate(
        family="trend",
        instruments=("ETHUSDT.BINANCE",),
        seed=42,
    )

    cycle = start_generated_paper_cycle(
        candidate=candidate,
        session_nonce="paper-session-2026-08-29T14:10:00Z",
    )

    assert cycle.receipt.strategy_id == candidate.strategy_id
    assert cycle.receipt.genome_hash == candidate.genome_hash
    assert cycle.receipt.engine == "nautilus_trader"
    assert cycle.receipt.engine_version == "1.231.0"
    assert cycle.receipt.venue == "SANDBOX"
    assert cycle.receipt.connected is True
    assert cycle.evidence.evidence_type == "paper_started"
    assert cycle.evidence.passed is True
    assert cycle.promotion.allowed is True
    assert cycle.promotion.target is StrategyState.PAPER


def test_paper_session_nonce_is_required_for_promotable_session_identity():
    candidate = generate_candidate(
        family="trend",
        instruments=("ETHUSDT.BINANCE",),
        seed=43,
    )

    try:
        start_generated_paper_cycle(candidate=candidate, session_nonce="")
    except ValueError as exc:
        assert "session_nonce" in str(exc)
    else:
        raise AssertionError("empty paper session nonce must fail closed")
