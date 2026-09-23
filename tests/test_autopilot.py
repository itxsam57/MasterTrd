from __future__ import annotations

import mastertrd.autopilot as autopilot
from mastertrd.autopilot import AutopilotConfig
from mastertrd.local_jobs import LocalJobReceipt
from mastertrd.market_universe import MarketCandidate


def test_autopilot_config_round_trip(tmp_path):
    config = AutopilotConfig(
        enabled=True,
        products=("SPOT", "USD_M"),
        universe_size=6,
        recipes_per_cycle=2,
        seed_count=2,
        auto_prepare_paper=False,
        auto_start_paper=False,
        max_running_jobs=4,
    )
    path = autopilot.save_autopilot_config(config, tmp_path / "autopilot.json")
    assert autopilot.load_autopilot_config(path) == config


def test_recipe_batch_rotates_deterministically():
    first, cursor = autopilot._select_recipe_batch("SPOT", cursor=0, count=3)
    second, next_cursor = autopilot._select_recipe_batch("SPOT", cursor=cursor, count=3)
    assert len(first) == 3
    assert len(second) == 3
    assert first != second
    assert next_cursor == 6


def test_autopilot_cycle_launches_bounded_rotating_jobs(tmp_path, monkeypatch):
    launched = []

    monkeypatch.setattr(autopilot, "list_local_jobs", lambda root: [])
    monkeypatch.setattr(
        autopilot,
        "scheduled_public_recipe_ids",
        lambda product: ("ema-cross-fast", "atr-breakout-fast"),
    )
    monkeypatch.setattr(
        autopilot,
        "strategy_recipe_timeframes",
        lambda recipe_id: ("15m",),
    )
    monkeypatch.setattr(autopilot, "recommended_archive_months", lambda recipe_id: 2)

    def fake_launch(recipe_id, root, **kwargs):
        launched.append((recipe_id, kwargs))
        return LocalJobReceipt(
            job_id=f"job-{len(launched)}",
            kind="RESEARCH",
            recipe_id=recipe_id,
            status="RUNNING",
            pid=100 + len(launched),
            created_at="2026-09-23T00:00:00+00:00",
            finished_at=None,
            job_dir=str(tmp_path / f"job-{len(launched)}"),
            error=None,
            instruments=kwargs["instruments"],
            timeframe=kwargs["timeframe"],
            seed_start=kwargs["seed_start"],
            seed_stop=kwargs["seed_stop"],
            archive_months=kwargs["archive_months"],
            product=kwargs["product"],
        )

    monkeypatch.setattr(autopilot, "launch_research_job", fake_launch)

    markets = (
        MarketCandidate("SPOT", "BTCUSDT", "BTCUSDT.BINANCE", "BTC", "USDT", 100.0),
        MarketCandidate("SPOT", "ETHUSDT", "ETHUSDT.BINANCE", "ETH", "USDT", 90.0),
    )
    config = AutopilotConfig(
        products=("SPOT",),
        universe_size=2,
        recipes_per_cycle=2,
        seed_count=2,
        auto_prepare_paper=False,
        auto_start_paper=False,
        max_running_jobs=2,
    )
    state = autopilot.run_autopilot_cycle(
        config=config,
        job_root=tmp_path / "jobs",
        universe_root=tmp_path / "universe",
        state_path=tmp_path / "state.json",
        universe_loader=lambda *args, **kwargs: markets,
        service=object(),
    )
    assert len(state["last_launched"]) == 2
    assert [item[0] for item in launched] == ["ema-cross-fast", "atr-breakout-fast"]
    assert all(item[1]["seed_stop"] - item[1]["seed_start"] == 2 for item in launched)
    assert all(item[1]["product"] == "SPOT" for item in launched)


def test_autopilot_maintenance_reconciles_without_launching_research(tmp_path, monkeypatch):
    calls = {"paper": 0, "worker": 0}

    monkeypatch.setattr(
        autopilot,
        "_auto_prepare_paper",
        lambda service, *, job_root: calls.__setitem__("paper", calls["paper"] + 1)
        or {"configured": False, "reason": "waiting"},
    )
    monkeypatch.setattr(
        autopilot,
        "_ensure_paper_worker",
        lambda service, *, log_path: calls.__setitem__("worker", calls["worker"] + 1)
        or {"started": False, "reason": "waiting"},
    )

    config = AutopilotConfig(
        enabled=True,
        products=("SPOT",),
        universe_size=2,
        recipes_per_cycle=1,
        seed_count=1,
        auto_prepare_paper=True,
        auto_start_paper=True,
        max_running_jobs=1,
    )
    state = autopilot.run_autopilot_maintenance(
        config=config,
        job_root=tmp_path / "jobs",
        state_path=tmp_path / "state.json",
        service=object(),
    )

    assert state["maintenance_status"] == "OK"
    assert state["maintenance_paper_action"]["reason"] == "waiting"
    assert state["maintenance_paper_worker"]["reason"] == "waiting"
    assert calls == {"paper": 1, "worker": 1}


def test_auto_prepare_paper_never_mixes_spot_and_usdm_candidates(tmp_path, monkeypatch):
    candidates = [
        {"product": "SPOT", "manifest": {"strategy_id": "spot-a"}},
        {"product": "SPOT", "manifest": {"strategy_id": "spot-b"}},
        {"product": "USD_M", "manifest": {"strategy_id": "perp-a"}},
        {"product": "USD_M", "manifest": {"strategy_id": "perp-b"}},
        {"product": "USD_M", "manifest": {"strategy_id": "perp-c"}},
    ]
    monkeypatch.setattr(autopilot, "local_paper_candidates", lambda root: candidates)

    class Service:
        def __init__(self):
            self.received = None

        def paper_portfolio_configured(self):
            return False

        def provider_rows(self):
            return [{"provider_id": "binance", "product": "USD_M"}]

        def configure_paper_portfolio(self, manifests):
            self.received = list(manifests)
            return {"portfolio_id": "paper-usdm", "product": "USD_M"}

    service = Service()
    result = autopilot._auto_prepare_paper(service, job_root=tmp_path)

    assert result["configured"] is True
    assert result["selected_product"] == "USD_M"
    assert [item["strategy_id"] for item in service.received] == [
        "perp-a",
        "perp-b",
        "perp-c",
    ]


def test_auto_prepare_paper_requires_two_candidates_from_same_product(tmp_path, monkeypatch):
    monkeypatch.setattr(
        autopilot,
        "local_paper_candidates",
        lambda root: [
            {"product": "SPOT", "manifest": {"strategy_id": "spot-a"}},
            {"product": "USD_M", "manifest": {"strategy_id": "perp-a"}},
        ],
    )

    class Service:
        def paper_portfolio_configured(self):
            return False

    result = autopilot._auto_prepare_paper(Service(), job_root=tmp_path)
    assert result["configured"] is False
    assert result["reason"] == "fewer_than_two_qualified_same_product_candidates"
    assert result["candidate_counts"] == {"SPOT": 1, "USD_M": 1}


def test_auto_prepare_paper_ignores_stale_source_handoffs(tmp_path, monkeypatch):
    candidates = [
        {"product": "SPOT", "manifest": {"strategy_id": "stale", "current": False}},
        {"product": "SPOT", "manifest": {"strategy_id": "spot-a", "current": True}},
        {"product": "SPOT", "manifest": {"strategy_id": "spot-b", "current": True}},
    ]
    monkeypatch.setattr(autopilot, "local_paper_candidates", lambda root: candidates)

    class Service:
        def __init__(self):
            self.received = None

        def paper_candidate_matches_current_source(self, manifest):
            return bool(manifest.get("current"))

        def paper_portfolio_configured(self):
            return False

        def provider_rows(self):
            return [{"provider_id": "binance", "product": "SPOT"}]

        def configure_paper_portfolio(self, manifests):
            self.received = list(manifests)
            return {"portfolio_id": "paper-spot", "product": "SPOT"}

    service = Service()
    result = autopilot._auto_prepare_paper(service, job_root=tmp_path)
    assert result["configured"] is True
    assert [item["strategy_id"] for item in service.received] == ["spot-a", "spot-b"]
