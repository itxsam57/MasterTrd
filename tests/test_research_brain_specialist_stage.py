from mastertrd.multi_leg_validation import MultiLegStressPolicy, MultiLegStressReport
from mastertrd.research.generator import generate_candidate
from mastertrd.research_brain import evaluate_research_specialist_candidate
from mastertrd.specialist_orchestrator import SpecialistInputs


def _candidate():
    return generate_candidate(
        family="stat_arb",
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed=17,
    )


def test_research_specialist_candidate_runs_real_typed_gate():
    candidate = _candidate()
    report = MultiLegStressReport(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash="multileg-dataset-v1",
        code_hash="research-code-v1",
        engine="nautilus_trader",
        engine_version="1.231.0",
        expected_legs=2,
        completed_cycles=4,
        leg_fill_counts=(4, 4),
        residual_exposure_ratio=0.01,
        slippage_bps=1.0,
    )
    policy = MultiLegStressPolicy(
        min_completed_cycles=2,
        max_leg_fill_skew=0.10,
        max_residual_exposure_ratio=0.05,
        max_slippage_bps=5.0,
    )

    outcome = evaluate_research_specialist_candidate(
        candidate,
        score=0.25,
        inputs=SpecialistInputs(
            multi_leg_report=report,
            multi_leg_policy=policy,
        ),
    )

    assert outcome["passed"] is True
    assert outcome["reason"] == "specialist_evidence_passed"
    assert outcome["score"] == 0.25
    assert [item["evidence_type"] for item in outcome["evidence"]] == [
        "multi_leg_execution_stress"
    ]
    assert outcome["evidence"][0]["strategy_id"] == candidate.strategy_id
    assert outcome["evidence"][0]["genome_hash"] == candidate.genome_hash


def test_research_specialist_candidate_reports_missing_inputs_precisely():
    candidate = _candidate()

    outcome = evaluate_research_specialist_candidate(
        candidate,
        score=-0.1,
        inputs=SpecialistInputs(),
    )

    assert outcome["passed"] is False
    assert outcome["reason"] == "specialist_inputs_missing:multi_leg_execution_stress"
    assert outcome["evidence"] == []
