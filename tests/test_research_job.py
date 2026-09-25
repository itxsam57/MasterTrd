from __future__ import annotations

from datetime import date, datetime, timezone
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import mastertrd.research_job as research_job


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "autonomous-research.yml"


def test_autonomous_research_workflow_delegates_to_checked_in_job():
    text = WORKFLOW.read_text(encoding="utf-8")
    lower = text.lower()

    assert "python -m mastertrd.research_job" in lower
    assert "python - <<'py'" not in lower
    assert "generate_candidate(" not in lower
    assert "family='trend'" not in lower
    assert "seed=42" not in lower


def test_default_research_job_plan_is_broad_and_blocks_missing_specialist_data():
    spec = importlib.util.find_spec("mastertrd.research_job")
    assert spec is not None, "checked-in mastertrd.research_job entrypoint is required"
    module = importlib.import_module("mastertrd.research_job")

    plan = module.default_research_job_plan()

    assert len(plan.requested_families) > 1
    assert len(plan.instruments) > 1
    assert plan.seed_stop - plan.seed_start > 1
    assert "trend" in plan.runnable_families
    assert "momentum" in plan.runnable_families

    blocked = {item.family: item.reason for item in plan.blocked_families}
    assert blocked["options"] == "qualifying_public_option_data_unavailable"
    assert blocked["scalping"] == "qualifying_public_tick_data_unavailable"
    assert blocked["market_making"] == "qualifying_public_l2_data_unavailable"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"requested_families": (), "runnable_families": ("trend",)}, "requested and runnable"),
        ({"requested_families": ("trend",), "runnable_families": ("momentum",)}, "must be requested"),
        ({"instruments": ("BTCUSDT.BINANCE",)}, "at least two instruments"),
        ({"seed_start": 3, "seed_stop": 3}, "seed_stop"),
        ({"archive_months": 1}, "archive_months"),
    ],
)
def test_research_job_plan_rejects_invalid_scheduled_contracts(kwargs, message):
    values = {
        "requested_families": ("trend",),
        "runnable_families": ("trend",),
        "blocked_families": (),
        "instruments": ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        "seed_start": 1,
        "seed_stop": 2,
        "archive_months": 2,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        research_job.ResearchJobPlan(**values)


def test_stable_archive_periods_skip_immediately_previous_month():
    assert research_job._stable_archive_periods(today=date(2026, 8, 31), count=3) == (
        "2026-04",
        "2026-05",
        "2026-06",
    )
    with pytest.raises(ValueError, match="positive"):
        research_job._stable_archive_periods(today=date(2026, 8, 31), count=0)


def test_checksum_parser_accepts_sha256_and_rejects_untrusted_responses():
    digest = "A" * 64
    assert research_job._checksum_from_response(f"{digest}  archive.zip\n") == digest.lower()

    for text in ("", "abc", "g" * 64):
        with pytest.raises(RuntimeError, match="invalid Binance checksum"):
            research_job._checksum_from_response(text)


def test_read_verified_public_archive_uses_checksum_and_download(monkeypatch, tmp_path):
    checksum = "a" * 64
    calls = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return f"{checksum}  file.zip\n".encode()

    monkeypatch.setattr(research_job, "binance_kline_url", lambda **kwargs: "https://data.example/file.zip")
    monkeypatch.setattr(research_job, "urlopen", lambda url, timeout: _Response())
    monkeypatch.setattr(
        research_job,
        "_download",
        lambda url, destination: calls.update(url=url, destination=destination),
    )
    sentinel = object()

    def fake_read(path, *, expected_sha256, symbol, interval, instrument_id=None):
        calls.update(
            read_path=path,
            expected_sha256=expected_sha256,
            symbol=symbol,
            interval=interval,
        )
        return sentinel

    monkeypatch.setattr(research_job, "read_binance_archive", fake_read)

    result = research_job._read_verified_public_archive(
        data_dir=tmp_path,
        symbol="BTCUSDT",
        instrument_id="BTCUSDT.BINANCE",
        interval="1h",
        period="2026-06",
    )

    assert result is sentinel
    assert calls["url"] == "https://data.example/file.zip"
    assert calls["destination"] == tmp_path / "file.zip"
    assert calls["expected_sha256"] == checksum
    assert calls["symbol"] == "BTCUSDT"
    assert calls["interval"] == "1h"


def test_manifest_payload_is_public_safe():
    manifest = SimpleNamespace(
        source="binance-public-data",
        venue="BINANCE",
        instrument="BTCUSDT.BINANCE",
        timeframe="1h",
        first_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
        last_timestamp=datetime(2026, 5, 31, tzinfo=timezone.utc),
        row_count=744,
        file_sha256="a" * 64,
        dataset_hash="dataset-v1",
    )

    payload = research_job._manifest_payload(SimpleNamespace(manifest=manifest), period="2026-05")

    assert payload["period"] == "2026-05"
    assert payload["instrument"] == "BTCUSDT.BINANCE"
    assert payload["first_timestamp"] == "2026-05-01T00:00:00+00:00"
    assert payload["file_sha256"] == "a" * 64


def test_load_public_instruments_uses_repository_loader(monkeypatch):
    seen = []
    monkeypatch.setattr(
        research_job,
        "load_public_binance_instrument",
        lambda instrument_id, *, product="SPOT": seen.append((instrument_id, product)) or f"instrument:{instrument_id}",
    )

    loaded = research_job._load_public_instruments(("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"))

    assert seen == [("BTCUSDT.BINANCE", "SPOT"), ("ETHUSDT.BINANCE", "SPOT")]
    assert loaded["BTCUSDT.BINANCE"] == "instrument:BTCUSDT.BINANCE"


def test_dataset_for_timeframe_builds_bar_only_verified_dataset(monkeypatch, tmp_path):
    btc = SimpleNamespace(raw_symbol=SimpleNamespace(value="BTCUSDT"))
    eth = SimpleNamespace(raw_symbol=SimpleNamespace(value="ETHUSDT"))
    instruments = {"BTCUSDT.BINANCE": btc, "ETHUSDT.BINANCE": eth}
    reads = []

    def fake_archive(**kwargs):
        reads.append(kwargs)
        token = f"{kwargs['instrument_id']}:{kwargs['period']}"
        manifest = SimpleNamespace(
            source="binance-public-data",
            venue="BINANCE",
            instrument=kwargs["instrument_id"],
            timeframe=kwargs["interval"],
            first_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
            last_timestamp=datetime(2026, 5, 2, tzinfo=timezone.utc),
            row_count=1,
            file_sha256="b" * 64,
            dataset_hash=f"hash:{token}",
        )
        timestamp = datetime(
            int(kwargs["period"][:4]),
            int(kwargs["period"][5:7]),
            1,
            tzinfo=timezone.utc,
        )
        return SimpleNamespace(
            bars=(SimpleNamespace(timestamp=timestamp, token=token),),
            manifest=manifest,
        )

    monkeypatch.setattr(research_job, "_read_verified_public_archive", fake_archive)
    monkeypatch.setattr(research_job, "dataset_hash_for_bars", lambda bars: "combined:" + "|".join(bar.token for bar in bars))

    dataset, manifests = research_job._dataset_for_timeframe(
        instrument_ids=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        instruments=instruments,
        timeframe="1h",
        periods=("2026-05", "2026-06"),
        data_dir=tmp_path,
    )

    assert len(reads) == 4
    assert dataset.dataset_hash.startswith("combined:")
    assert len(dataset.bars_by_instrument["BTCUSDT.BINANCE"]) == 2
    assert dataset.available_data_levels["BTCUSDT.BINANCE"] == frozenset({"BAR"})
    assert {item["period"] for item in manifests} == {"2026-05", "2026-06"}


def test_dataset_for_timeframe_fails_closed_for_bad_metadata_or_empty_bars(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="missing raw symbol"):
        research_job._dataset_for_timeframe(
            instrument_ids=("BTCUSDT.BINANCE",),
            instruments={"BTCUSDT.BINANCE": SimpleNamespace(raw_symbol=SimpleNamespace(value=""))},
            timeframe="1h",
            periods=("2026-05",),
            data_dir=tmp_path,
        )

    monkeypatch.setattr(
        research_job,
        "_read_verified_public_archive",
        lambda **kwargs: SimpleNamespace(
            bars=(),
            manifest=SimpleNamespace(
                source="binance-public-data",
                venue="BINANCE",
                instrument=kwargs["instrument_id"],
                timeframe=kwargs["interval"],
                first_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
                last_timestamp=datetime(2026, 5, 1, tzinfo=timezone.utc),
                row_count=0,
                file_sha256="c" * 64,
                dataset_hash="empty",
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="no verified public bars"):
        research_job._dataset_for_timeframe(
            instrument_ids=("BTCUSDT.BINANCE",),
            instruments={"BTCUSDT.BINANCE": SimpleNamespace(raw_symbol=SimpleNamespace(value="BTCUSDT"))},
            timeframe="1h",
            periods=("2026-05",),
            data_dir=tmp_path,
        )


def test_public_run_payload_contains_only_public_candidate_evidence():
    finalist = SimpleNamespace(
        strategy_id="S-1",
        genome_hash="g-1",
        state=SimpleNamespace(value="hidden_pass"),
        score=1.25,
        reason="qualified",
    )
    report = SimpleNamespace(
        run_id="run-1",
        generated=4,
        stored=2,
        paper_queued=1,
        resumed=False,
        finalists=(finalist,),
    )

    payload = research_job._public_run_payload(
        family="trend",
        seed=40,
        timeframe="1h",
        report=report,
        manifests=({"file_sha256": "d" * 64},),
    )

    assert payload["family"] == "trend"
    assert payload["seed"] == 40
    assert payload["finalists"] == [
        {
            "strategy_id": "S-1",
            "genome_hash": "g-1",
            "state": "hidden_pass",
            "score": 1.25,
            "reason": "qualified",
        }
    ]


def test_run_research_job_executes_all_runnable_family_seed_pairs_and_reuses_timeframe_data(monkeypatch, tmp_path):
    plan = research_job.ResearchJobPlan(
        requested_families=("trend", "momentum", "options"),
        runnable_families=("trend", "momentum"),
        blocked_families=(research_job.ResearchJobBlocker("options", "qualifying_public_option_data_unavailable"),),
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed_start=40,
        seed_stop=42,
        archive_months=2,
    )
    calls = {"datasets": 0, "runs": []}

    class _Memory:
        closed = False

        def close(self):
            self.closed = True

    memory = _Memory()
    monkeypatch.setattr(research_job, "DuckDbResearchMemory", lambda path: memory)
    monkeypatch.setattr(research_job, "_stable_archive_periods", lambda count: ("2026-05", "2026-06"))
    monkeypatch.setattr(
        research_job,
        "_load_public_instruments",
        lambda ids, **kwargs: {instrument_id: object() for instrument_id in ids},
    )
    monkeypatch.setattr(
        research_job,
        "generate_candidate",
        lambda **kwargs: SimpleNamespace(timeframe="1h"),
    )

    dataset = SimpleNamespace(dataset_hash="dataset-v1")

    def fake_dataset(**kwargs):
        calls["datasets"] += 1
        return dataset, ({"file_sha256": "e" * 64},)

    monkeypatch.setattr(research_job, "_dataset_for_timeframe", fake_dataset)

    def fake_run(config, supplied_dataset, supplied_memory, *, code_hash, lock_hash):
        calls["runs"].append((config.families, config.seed_start, supplied_dataset, supplied_memory, code_hash, lock_hash))
        return SimpleNamespace(
            run_id=f"run-{config.families[0]}-{config.seed_start}",
            generated=1,
            stored=1,
            paper_queued=0,
            resumed=False,
            finalists=(),
        )

    monkeypatch.setattr(research_job, "run_research_brain", fake_run)

    report = research_job.run_research_job(
        plan,
        artifact_dir=tmp_path,
        code_hash="code-v1",
        lock_hash="lock-v1",
    )

    assert calls["datasets"] == 1
    assert len(calls["runs"]) == 4
    assert memory.closed is True
    assert report["schema_version"] == 1
    assert report["periods"] == ["2026-05", "2026-06"]
    assert len(report["runs"]) == 4
    assert report["plan"]["blocked_families"] == [
        {"family": "options", "reason": "qualifying_public_option_data_unavailable"}
    ]


@pytest.mark.parametrize(("code_hash", "lock_hash"), [("", "lock"), ("code", "")])
def test_run_research_job_requires_provenance_hashes(tmp_path, code_hash, lock_hash):
    with pytest.raises(ValueError, match="code_hash and lock_hash"):
        research_job.run_research_job(
            research_job.default_research_job_plan(),
            artifact_dir=tmp_path,
            code_hash=code_hash,
            lock_hash=lock_hash,
        )


def test_main_writes_public_safe_json_report(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    Path("uv.lock").write_bytes(b"locked")
    monkeypatch.setenv("GITHUB_SHA", "code-v1")
    monkeypatch.setenv("MASTERTRD_RESEARCH_ARTIFACT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(research_job, "default_research_job_plan", lambda **kwargs: object())
    monkeypatch.setattr(
        research_job,
        "run_research_job",
        lambda plan, **kwargs: {"schema_version": 1, "runs": [{"family": "trend"}]},
    )

    assert research_job.main() == 0

    payload = json.loads((tmp_path / "out" / "research-report.json").read_text(encoding="utf-8"))
    assert payload == {"runs": [{"family": "trend"}], "schema_version": 1}
    printed = json.loads(capsys.readouterr().out)
    assert printed["runs"] == 1
    assert printed["research_report"].endswith("research-report.json")


def test_main_fails_closed_without_code_hash_or_lock(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("MASTERTRD_CODE_HASH", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_SHA or MASTERTRD_CODE_HASH"):
        research_job.main()

    monkeypatch.setenv("MASTERTRD_CODE_HASH", "code-v1")
    with pytest.raises(RuntimeError, match="uv.lock is required"):
        research_job.main()


def test_scheduled_research_uses_promotion_grade_validation_policies():
    from mastertrd.research_job import _scheduled_validation_policies

    robust, advanced, transfer, hidden = _scheduled_validation_policies()

    assert robust.min_trades_per_slice == 5
    assert robust.min_profitable_slice_ratio == 1.0
    assert robust.max_drawdown == 0.20
    assert robust.min_stressed_return == 0.0
    assert robust.max_return_degradation == 0.60
    assert robust.min_stable_neighbor_ratio == 0.67
    assert advanced.min_evaluations == 1
    assert advanced.min_trades_per_evaluation == 5
    assert advanced.min_positive_ratio == 1.0
    assert advanced.max_drawdown == 0.25
    assert advanced.min_monte_carlo_survival_ratio == 1.0
    assert advanced.max_monte_carlo_loss == -0.10
    assert transfer.min_transfer_assets == 1
    assert transfer.min_trades_per_asset == 5
    assert transfer.min_pass_ratio == 1.0
    assert transfer.min_total_return == 0.0
    assert transfer.max_drawdown == 0.25
    assert hidden.min_trades_per_evaluation == 5
    assert hidden.min_total_return == 0.0
    assert hidden.max_drawdown == 0.20
    assert hidden.min_regime_pass_ratio == 0.67


def test_scheduled_research_prices_in_normal_and_stressed_execution_costs():
    from mastertrd.research_job import _scheduled_execution_costs

    costs = _scheduled_execution_costs()

    assert costs == {
        "fees": 0.0010,
        "slippage": 0.0005,
        "stressed_fees": 0.0020,
        "stressed_slippage": 0.0020,
    }


def test_scheduled_validation_depth_covers_slow_strategy_warmup_and_hidden_folds():
    from mastertrd.research_job import _archive_months_for_recipe, _scheduled_validation_window

    assert _scheduled_validation_window("ema-cross-balanced") >= 150
    assert _archive_months_for_recipe("ema-cross-balanced") >= 6
    assert _scheduled_validation_window("pullback-balanced") >= 150
    assert _archive_months_for_recipe("pullback-balanced") >= 26
    assert _scheduled_validation_window("long-trend-balanced") >= 350
    assert _archive_months_for_recipe("long-trend-balanced") >= 60


def test_usdm_public_plan_uses_perpetual_instruments():
    plan = research_job.research_job_plan_for_recipe("ema-cross-futures", product="USD_M")
    assert plan.product == "USD_M"
    assert plan.instruments == (
        "BTCUSDT-PERP.BINANCE",
        "ETHUSDT-PERP.BINANCE",
        "SOLUSDT-PERP.BINANCE",
        "XRPUSDT-PERP.BINANCE",
    )
    assert "ema-cross-futures" in research_job.scheduled_public_recipe_ids("USD_M")


def test_usdm_archive_uses_futures_path_and_perpetual_identity(monkeypatch, tmp_path):
    checksum = "a" * 64
    seen = {}

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return f"{checksum} file.zip\n".encode()

    monkeypatch.setattr(research_job, "_read_url_text_with_retry", lambda *args, **kwargs: f"{checksum} file.zip")
    monkeypatch.setattr(research_job, "_download", lambda url, destination: None)
    monkeypatch.setattr(
        research_job,
        "binance_kline_url",
        lambda **kwargs: seen.update(kwargs) or "https://data.example/BTCUSDT-15m.zip",
    )
    monkeypatch.setattr(
        research_job,
        "read_binance_archive",
        lambda path, **kwargs: seen.update(kwargs) or object(),
    )
    research_job._read_verified_public_archive(
        data_dir=tmp_path,
        symbol="BTCUSDT",
        instrument_id="BTCUSDT-PERP.BINANCE",
        interval="15m",
        period="2026-06",
        product="USD_M",
    )
    assert seen["market"] == "um"
    assert seen["instrument_id"] == "BTCUSDT-PERP.BINANCE"


def test_usdm_research_job_can_queue_qualified_candidate_for_paper(monkeypatch, tmp_path):
    from dataclasses import replace

    plan = research_job.research_job_plan_for_recipe(
        "ema-cross-futures",
        product="USD_M",
    )
    plan = replace(
        plan,
        seed_start=40,
        seed_stop=41,
        archive_months=2,
        timeframes=("15m",),
    )
    captured = {}

    class Memory:
        def close(self):
            pass

    monkeypatch.setattr(research_job, "DuckDbResearchMemory", lambda path: Memory())
    monkeypatch.setattr(
        research_job,
        "_stable_archive_periods",
        lambda count: ("2026-05", "2026-06"),
    )
    monkeypatch.setattr(
        research_job,
        "_load_public_instruments",
        lambda ids, **kwargs: {instrument_id: object() for instrument_id in ids},
    )
    dataset = SimpleNamespace(dataset_hash="dataset-usdm")
    monkeypatch.setattr(
        research_job,
        "_dataset_for_timeframe",
        lambda **kwargs: (dataset, ({"file_sha256": "f" * 64},)),
    )

    def fake_run(config, *_args, **_kwargs):
        captured["paper_queue_cap"] = config.paper_queue_cap
        captured["starting_balances"] = config.starting_balances
        return SimpleNamespace(
            run_id="run-usdm",
            generated=1,
            stored=1,
            paper_queued=0,
            resumed=False,
            finalists=(),
        )

    monkeypatch.setattr(research_job, "run_research_brain", fake_run)
    report = research_job.run_research_job(
        plan,
        artifact_dir=tmp_path,
        code_hash="code-usdm",
        lock_hash="lock-usdm",
    )

    assert report["plan"]["product"] == "USD_M"
    assert captured["paper_queue_cap"] == 1
    assert captured["starting_balances"] == ("100000 USDT",)


def test_stat_arb_public_plan_uses_four_usdm_markets_for_independent_transfer():
    plan = research_job.research_job_plan_for_recipe(
        "pairs-cointegration-balanced",
        product="USD_M",
    )
    assert plan.runnable_recipe_ids == ("pairs-cointegration-balanced",)
    assert len(plan.instruments) == 4
    assert plan.instruments[:2] == (
        "BTCUSDT-PERP.BINANCE",
        "ETHUSDT-PERP.BINANCE",
    )
    assert "pairs-cointegration-balanced" in research_job.scheduled_public_recipe_ids("USD_M")
    assert "pairs-cointegration-balanced" not in research_job.scheduled_public_recipe_ids("SPOT")
    assert (
        research_job.research_recipe_coverage("SPOT")["pairs-cointegration-balanced"]
        == "blocked:spot_cash_short_leg_execution_unavailable"
    )


def test_stat_arb_research_stays_out_of_paper_until_forward_multileg_is_admitted(
    monkeypatch,
    tmp_path,
):
    from dataclasses import replace

    plan = research_job.research_job_plan_for_recipe(
        "pairs-cointegration-balanced",
        product="USD_M",
    )
    plan = replace(
        plan,
        seed_start=40,
        seed_stop=41,
        archive_months=2,
        timeframes=("15m",),
    )
    captured = {}

    class Memory:
        def close(self):
            pass

    monkeypatch.setattr(research_job, "DuckDbResearchMemory", lambda path: Memory())
    monkeypatch.setattr(
        research_job,
        "_stable_archive_periods",
        lambda count: ("2026-05", "2026-06"),
    )
    monkeypatch.setattr(
        research_job,
        "_load_public_instruments",
        lambda ids, **kwargs: {instrument_id: object() for instrument_id in ids},
    )
    dataset = SimpleNamespace(dataset_hash="dataset-stat-arb")
    monkeypatch.setattr(
        research_job,
        "_dataset_for_timeframe",
        lambda **kwargs: (dataset, ({"file_sha256": "e" * 64},)),
    )

    def fake_run(config, *_args, **_kwargs):
        captured["instruments"] = config.instruments
        captured["paper_queue_cap"] = config.paper_queue_cap
        captured["validation_window"] = config.validation_window
        captured["multi_leg_policy"] = config.multi_leg_policy
        captured["instrument_sets"] = config.instrument_sets
        captured["validation_budget"] = config.validation_budget
        return SimpleNamespace(
            run_id="run-stat-arb",
            generated=1,
            stored=1,
            paper_queued=0,
            resumed=False,
            finalists=(),
        )

    monkeypatch.setattr(research_job, "run_research_brain", fake_run)
    report = research_job.run_research_job(
        plan,
        artifact_dir=tmp_path,
        code_hash="code-stat-arb",
        lock_hash="lock-stat-arb",
    )

    assert report["plan"]["product"] == "USD_M"
    assert len(captured["instruments"]) == 4
    assert captured["paper_queue_cap"] == 0
    assert captured["validation_window"] == 300
    assert captured["multi_leg_policy"].min_completed_cycles == 1
    assert captured["multi_leg_policy"].max_leg_fill_skew == 0.0
    assert captured["instrument_sets"] == (
        ("BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"),
        ("SOLUSDT-PERP.BINANCE", "XRPUSDT-PERP.BINANCE"),
    )
    assert captured["validation_budget"] == 2


def test_crypto_rotation_public_plan_is_exact_multileg_but_paper_remains_closed(
    monkeypatch,
    tmp_path,
):
    from dataclasses import replace

    plan = research_job.research_job_plan_for_recipe(
        "crypto-rotation",
        product="SPOT",
    )
    assert len(plan.instruments) == 4
    assert "crypto-rotation" in research_job.scheduled_public_recipe_ids("SPOT")
    assert "crypto-rotation" in research_job.scheduled_public_recipe_ids("USD_M")

    plan = replace(
        plan,
        seed_start=50,
        seed_stop=51,
        archive_months=2,
        timeframes=("1h",),
    )
    captured = {}

    class Memory:
        def close(self):
            pass

    monkeypatch.setattr(research_job, "DuckDbResearchMemory", lambda path: Memory())
    monkeypatch.setattr(
        research_job,
        "_stable_archive_periods",
        lambda count: ("2026-05", "2026-06"),
    )
    monkeypatch.setattr(
        research_job,
        "_load_public_instruments",
        lambda ids, **kwargs: {instrument_id: object() for instrument_id in ids},
    )
    dataset = SimpleNamespace(dataset_hash="dataset-rotation")
    monkeypatch.setattr(
        research_job,
        "_dataset_for_timeframe",
        lambda **kwargs: (dataset, ({"file_sha256": "d" * 64},)),
    )

    def fake_run(config, *_args, **_kwargs):
        captured["instrument_sets"] = config.instrument_sets
        captured["validation_budget"] = config.validation_budget
        captured["paper_queue_cap"] = config.paper_queue_cap
        return SimpleNamespace(
            run_id="run-rotation",
            generated=1,
            stored=1,
            paper_queued=0,
            resumed=False,
            finalists=(),
        )

    monkeypatch.setattr(research_job, "run_research_brain", fake_run)
    report = research_job.run_research_job(
        plan,
        artifact_dir=tmp_path,
        code_hash="code-rotation",
        lock_hash="lock-rotation",
    )

    assert report["plan"]["product"] == "SPOT"
    assert captured["instrument_sets"] == (
        ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        ("SOLUSDT.BINANCE", "XRPUSDT.BINANCE"),
    )
    assert captured["validation_budget"] == 2
    assert captured["paper_queue_cap"] == 0
