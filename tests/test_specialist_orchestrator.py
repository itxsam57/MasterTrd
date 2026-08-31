from __future__ import annotations

from mastertrd.genome import StrategyGenome
from mastertrd.multi_leg_validation import (
    MultiLegStressPolicy,
    MultiLegStressReport,
)
from mastertrd.options_validation import OptionsStressPolicy, OptionsStressReport
from mastertrd.specialist_orchestrator import SpecialistInputs, run_specialist_gate


def _candidate(family: str, instruments: tuple[str, ...]) -> StrategyGenome:
    return StrategyGenome(
        strategy_id=f"SPECIALIST-{family}",
        family=family,
        style=family,
        instruments=instruments,
        timeframe="tick" if family in {"market_making", "order_book"} else "1h",
        entry={"type": "test"},
        exit={"type": "test"},
        data_requirements=("L2",) if family in {"market_making", "order_book"} else ("BAR",),
        allow_short=family != "options",
    )


def _multi_policy() -> MultiLegStressPolicy:
    return MultiLegStressPolicy(
        min_completed_cycles=10,
        max_leg_fill_skew=0.10,
        max_residual_exposure_ratio=0.05,
        max_slippage_bps=12.0,
    )


def _multi_report(candidate: StrategyGenome, *, residual: float = 0.01) -> MultiLegStressReport:
    return MultiLegStressReport(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash="multileg-real-session",
        code_hash="code-multileg",
        engine="nautilus_trader",
        engine_version="1.231.0",
        expected_legs=2,
        completed_cycles=12,
        leg_fill_counts=(12, 12),
        residual_exposure_ratio=residual,
        slippage_bps=5.0,
    )


def _options_policy() -> OptionsStressPolicy:
    return OptionsStressPolicy(
        max_abs_delta_error=0.05,
        max_abs_gamma_error=0.02,
        max_abs_vega_error=0.05,
        max_abs_theta_error=0.05,
        max_surface_price_error_ratio=0.08,
        max_surface_monotonicity_violations=0,
        max_surface_convexity_violations=0,
        min_surface_points=20,
    )


def _options_report(candidate: StrategyGenome) -> OptionsStressReport:
    return OptionsStressReport(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash="options-real-session",
        code_hash="code-options",
        engine="nautilus_trader",
        engine_version="1.231.0",
        delta_error=0.01,
        gamma_error=0.005,
        vega_error=0.02,
        theta_error=0.02,
        surface_points=30,
        max_surface_price_error_ratio=0.04,
        monotonicity_violations=0,
        convexity_violations=0,
    )


def test_standard_family_has_no_specialist_gate_to_fake() -> None:
    candidate = _candidate("trend", ("BTCUSDT.BINANCE",))

    result = run_specialist_gate(candidate, SpecialistInputs())

    assert result.passed is True
    assert result.evidence == ()
    assert result.missing_evidence == frozenset()
    assert result.failed_evidence == frozenset()
    assert result.reason == "standard_execution_path"


def test_required_specialist_input_missing_blocks_with_machine_readable_reason() -> None:
    multi = _candidate("stat_arb", ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"))
    hft = _candidate("market_making", ("BTCUSDT.BINANCE",))

    multi_result = run_specialist_gate(multi, SpecialistInputs())
    hft_result = run_specialist_gate(hft, SpecialistInputs())

    assert multi_result.passed is False
    assert multi_result.missing_evidence == frozenset({"multi_leg_execution_stress"})
    assert multi_result.reason == "specialist_inputs_missing:multi_leg_execution_stress"
    assert hft_result.passed is False
    assert hft_result.missing_evidence == frozenset({"hft_real_l2"})
    assert hft_result.reason == "specialist_inputs_missing:hft_real_l2"


def test_real_multileg_report_is_evaluated_instead_of_auto_quarantined() -> None:
    candidate = _candidate("stat_arb", ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"))

    result = run_specialist_gate(
        candidate,
        SpecialistInputs(
            multi_leg_report=_multi_report(candidate),
            multi_leg_policy=_multi_policy(),
        ),
    )

    assert result.passed is True
    assert [record.evidence_type for record in result.evidence] == ["multi_leg_execution_stress"]
    assert result.reason == "specialist_evidence_passed"


def test_failed_multileg_report_stays_failed_and_is_not_rewritten_as_missing() -> None:
    candidate = _candidate("stat_arb", ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"))

    result = run_specialist_gate(
        candidate,
        SpecialistInputs(
            multi_leg_report=_multi_report(candidate, residual=0.20),
            multi_leg_policy=_multi_policy(),
        ),
    )

    assert result.passed is False
    assert result.missing_evidence == frozenset()
    assert result.failed_evidence == frozenset({"multi_leg_execution_stress"})
    assert result.reason == "specialist_evidence_failed:multi_leg_execution_stress"


def test_real_options_report_produces_both_required_evidence_records() -> None:
    candidate = _candidate("options", ("BTC-13JAN23-16000-P.DERIBIT",))

    result = run_specialist_gate(
        candidate,
        SpecialistInputs(
            options_report=_options_report(candidate),
            options_policy=_options_policy(),
        ),
    )

    assert result.passed is True
    assert {record.evidence_type for record in result.evidence} == {
        "options_greeks_validation",
        "volatility_surface_stress",
    }
    assert result.missing_evidence == frozenset()
    assert result.failed_evidence == frozenset()
