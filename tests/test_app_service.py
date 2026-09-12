from mastertrd.app_service import AppService
from mastertrd.strategy_universe import STRATEGY_RECIPES


def test_app_service_exposes_full_strategy_catalog():
    rows = AppService().strategy_rows()
    assert len(rows) == len(STRATEGY_RECIPES)
    assert len(rows) >= 189
    assert {"recipe_id", "name", "family", "readiness", "assets", "horizons", "blocker"} <= rows[0].keys()


def test_snapshot_is_safe_by_default(monkeypatch):
    monkeypatch.delenv("MASTERTRD_MODE", raising=False)
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)
    snapshot = AppService().snapshot()
    assert snapshot["mode"] == "PAPER"
    assert snapshot["live_enabled"] is False
    assert snapshot["strategy_count"] == len(STRATEGY_RECIPES)
