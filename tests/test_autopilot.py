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
