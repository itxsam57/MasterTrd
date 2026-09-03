from __future__ import annotations

import inspect
from pathlib import Path

from mastertrd.genome import StrategyGenome
from mastertrd.paper_evidence import PaperStartReceipt
from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal
from mastertrd.strategy_families import DataLevel, family_spec
from mastertrd.strategy_universe import AssetClass, RecipeReadiness, STRATEGY_RECIPES


NS = 1_000_000_000


def _ema_genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-final-hardening",
        family="trend",
        style="trend",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="15m",
        entry={"kind": "ema_cross", "fast": 11, "slow": 34, "trade_size": "0.01"},
        exit={"kind": "cross_reverse"},
    )


def _receipt(candidate: StrategyGenome) -> PaperStartReceipt:
    return PaperStartReceipt(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        session_id="final-hardening-session",
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version="1.231.0",
        connected=True,
    )


def test_promotion_grade_trend_does_not_compile_to_nautilus_example_strategy():
    import mastertrd.nautilus_strategy as module

    source = inspect.getsource(module)
    assert "nautilus_trader.examples.strategies.ema_cross" not in source
    assert "RiskManagedEMACross" not in source


def test_bar_history_contract_exposes_conservative_restart_warmup():
    import mastertrd.execution_signals as signals
    import mastertrd.nautilus_paper as paper

    candidate = _ema_genome()
    required = signals.required_bar_history(candidate)
    assert required == 34
    assert paper.paper_bootstrap_bar_limit(candidate) >= required
    assert paper.paper_bootstrap_bar_limit(candidate) >= 100


def test_strategy_telemetry_is_integrity_covered_and_survives_restart(tmp_path):
    candidate = _ema_genome()
    started = 1_000 * NS
    journal = PaperSessionJournal(_receipt(candidate), code_hash="code-hardening", started_ns=started)
    journal.record_strategy_telemetry(
        {
            "bars_seen": 34,
            "bars_required": 34,
            "warmup_remaining": 0,
            "last_signal": "LONG",
            "last_signal_reason": "ema_cross",
            "orders_attempted": 1,
            "orders_rejected": 0,
            "last_risk_rejection": None,
        },
        timestamp_ns=started + NS,
    )
    path = tmp_path / "paper.json"
    store = JsonPaperSessionStore(path)
    store.save(journal)

    restored = store.load()
    assert restored.strategy_telemetry == journal.strategy_telemetry

    from mastertrd.paper_status import paper_status_payload

    status = paper_status_payload(restored, observed_ns=started + 2 * NS)
    assert status["bars_seen"] == 34
    assert status["bars_required"] == 34
    assert status["warmup_remaining"] == 0
    assert status["last_signal"] == "LONG"
    assert status["last_signal_reason"] == "ema_cross"
    assert status["orders_attempted"] == 1
    assert status["orders_rejected"] == 0


def test_scheduled_public_research_covers_every_compatible_executable_recipe():
    import mastertrd.research_job as research_job

    expected = {
        recipe.recipe_id
        for recipe in STRATEGY_RECIPES
        if recipe.readiness is RecipeReadiness.EXECUTABLE
        and AssetClass.CRYPTO in recipe.asset_classes
        and family_spec(recipe.family).min_data_level is DataLevel.BAR
        and family_spec(recipe.family).max_instruments == 1
    }
    scheduled = set(research_job.scheduled_public_recipe_ids())
    assert scheduled == expected
    assert len(scheduled) >= 25

    workflow = Path(".github/workflows/autonomous-research.yml").read_text(encoding="utf-8")
    for recipe_id in sorted(scheduled):
        assert f"- {recipe_id}" in workflow


def test_every_planned_recipe_is_classified_for_testing_or_explicitly_blocked():
    import mastertrd.research_job as research_job

    coverage = research_job.research_recipe_coverage()
    assert set(coverage) == {recipe.recipe_id for recipe in STRATEGY_RECIPES}
    assert set(coverage.values()) >= {"scheduled_public_bar"}
    assert all(
        disposition == "scheduled_public_bar" or disposition.startswith("blocked:")
        for disposition in coverage.values()
    )
