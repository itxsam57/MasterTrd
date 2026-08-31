from mastertrd.multi_leg_validation import MultiLegStressPolicy, MultiLegStressReport
from mastertrd.research.generator import generate_candidate
from mastertrd.research_brain import run_research_specialist_stage
from mastertrd.specialist_orchestrator import SpecialistInputs


def _validated_item(candidate, score=0.25):
    return {
        "genome": candidate.canonical_payload(),
        "passed": True,
        "score": score,
        "reason": "validated promotion evidence satisfied",
    }


def _stat_arb_candidate():
    return generate_candidate(
        family="stat_arb",
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed=17,
    )


def _passing_inputs(candidate):
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
    return SpecialistInputs(
        multi_leg_report=report,
        multi_leg_policy=policy,
    )


def test_research_specialist_stage_routes_candidate_keyed_inputs_and_persists_evidence():
    specialist = _stat_arb_candidate()
    standard = generate_candidate(
        family="trend",
        instruments=("BTCUSDT.BINANCE",),
        seed=19,
    )

    artifact = run_research_specialist_stage(
        (_validated_item(specialist), _validated_item(standard, score=0.1)),
        specialist_inputs_by_genome_hash={
            specialist.genome_hash: _passing_inputs(specialist),
        },
    )

    outcomes = artifact["outcomes"]
    by_hash = {
        item["genome"]["genome_hash"]: item
        for item in outcomes
    }
    specialist_outcome = by_hash[specialist.genome_hash]
    assert specialist_outcome["passed"] is True
    assert specialist_outcome["reason"] == "specialist_evidence_passed"
    assert [item["evidence_type"] for item in specialist_outcome["evidence"]] == [
        "multi_leg_execution_stress"
    ]

    standard_outcome = by_hash[standard.genome_hash]
    assert standard_outcome["passed"] is True
    assert standard_outcome["reason"] == "standard_execution_path"
    assert standard_outcome["evidence"] == []


def test_research_specialist_stage_marks_missing_inputs_precisely_and_preserves_prior_failures():
    specialist = _stat_arb_candidate()
    prior_failure = {
        "genome": specialist.canonical_payload(),
        "passed": False,
        "score": -1.0,
        "reason": "nautilus_validation_failed:ValueError:bad data",
    }

    missing = run_research_specialist_stage(
        (_validated_item(specialist),),
        specialist_inputs_by_genome_hash={},
    )["outcomes"][0]
    assert missing["passed"] is False
    assert missing["reason"] == "specialist_inputs_missing:multi_leg_execution_stress"
    assert missing["missing_evidence"] == ["multi_leg_execution_stress"]
    assert missing["evidence"] == []

    preserved = run_research_specialist_stage(
        (prior_failure,),
        specialist_inputs_by_genome_hash={specialist.genome_hash: _passing_inputs(specialist)},
    )["outcomes"][0]
    assert preserved == prior_failure
