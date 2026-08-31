from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping
from urllib.request import urlopen

from .data.archive import ArchiveReadResult, dataset_hash_for_bars, read_binance_archive
from .data.binance_public import binance_kline_url
from .memory_duckdb import DuckDbResearchMemory
from .nautilus_paper import load_public_binance_spot_instrument
from .research.generator import generate_candidate
from .research_brain import ResearchBrainConfig, ResearchDataset, run_research_brain
from .strategy_families import FAMILIES


@dataclass(frozen=True, slots=True)
class ResearchJobBlocker:
    family: str
    reason: str


@dataclass(frozen=True, slots=True)
class ResearchJobPlan:
    requested_families: tuple[str, ...]
    runnable_families: tuple[str, ...]
    blocked_families: tuple[ResearchJobBlocker, ...]
    instruments: tuple[str, ...]
    seed_start: int
    seed_stop: int
    archive_months: int = 2

    def __post_init__(self) -> None:
        if not self.requested_families or not self.runnable_families:
            raise ValueError("research job requires requested and runnable families")
        if not set(self.runnable_families).issubset(self.requested_families):
            raise ValueError("runnable families must be requested")
        if len(self.instruments) < 2:
            raise ValueError("scheduled research requires at least two instruments")
        if self.seed_stop <= self.seed_start:
            raise ValueError("seed_stop must be greater than seed_start")
        if self.archive_months < 2:
            raise ValueError("archive_months must be at least two")


def default_research_job_plan() -> ResearchJobPlan:
    requested = tuple(FAMILIES)
    runnable = (
        "trend",
        "momentum",
        "breakout",
        "mean_reversion",
        "volatility",
    )
    reasons = {
        "stat_arb": "scheduled_multi_leg_validation_unavailable",
        "funding_basis": "scheduled_multi_leg_validation_unavailable",
        "delta_neutral": "scheduled_multi_leg_validation_unavailable",
        "portfolio": "scheduled_multi_leg_validation_unavailable",
        "swing": "scheduled_long_horizon_window_unavailable",
        "position": "scheduled_long_horizon_window_unavailable",
        "options": "qualifying_public_option_data_unavailable",
        "scalping": "qualifying_public_tick_data_unavailable",
        "grid": "qualifying_public_tick_data_unavailable",
        "market_making": "qualifying_public_l2_data_unavailable",
        "order_book": "qualifying_public_l2_data_unavailable",
        "cross_venue_arb": "qualifying_public_tick_data_unavailable",
    }
    blocked = tuple(
        ResearchJobBlocker(family=family, reason=reasons[family])
        for family in requested
        if family not in runnable
    )
    return ResearchJobPlan(
        requested_families=requested,
        runnable_families=runnable,
        blocked_families=blocked,
        instruments=("BTCUSDT.BINANCE", "ETHUSDT.BINANCE"),
        seed_start=40,
        seed_stop=43,
        archive_months=2,
    )


def _stable_archive_periods(*, today: date | None = None, count: int) -> tuple[str, ...]:
    if count <= 0:
        raise ValueError("archive period count must be positive")
    current = today or datetime.now(timezone.utc).date()
    first_this_month = current.replace(day=1)
    last_previous_month = first_this_month - timedelta(days=1)
    # Skip the immediately previous month so the public monthly archive and its
    # checksum have time to be finalized by Binance before an automated run.
    stable_month_end = last_previous_month.replace(day=1) - timedelta(days=1)
    cursor = stable_month_end.replace(day=1)
    periods: list[str] = []
    for _ in range(count):
        periods.append(cursor.strftime("%Y-%m"))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return tuple(reversed(periods))


def _checksum_from_response(text: str) -> str:
    token = text.strip().split()[0] if text.strip() else ""
    lowered = token.lower()
    if len(lowered) != 64 or any(ch not in "0123456789abcdef" for ch in lowered):
        raise RuntimeError("invalid Binance checksum response")
    return lowered


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=60) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def _read_verified_public_archive(
    *,
    data_dir: Path,
    symbol: str,
    instrument_id: str,
    interval: str,
    period: str,
) -> ArchiveReadResult:
    url = binance_kline_url(
        market="spot",
        symbol=symbol,
        interval=interval,
        period=period,
    )
    checksum_url = f"{url}.CHECKSUM"
    with urlopen(checksum_url, timeout=30) as response:
        checksum_text = response.read().decode("utf-8")
    expected_sha256 = _checksum_from_response(checksum_text)
    archive_path = data_dir / url.rsplit("/", 1)[-1]
    _download(url, archive_path)
    return read_binance_archive(
        archive_path,
        expected_sha256=expected_sha256,
        symbol=instrument_id,
        interval=interval,
    )


def _manifest_payload(result: ArchiveReadResult, *, period: str) -> dict[str, object]:
    manifest = result.manifest
    return {
        "source": manifest.source,
        "venue": manifest.venue,
        "instrument": manifest.instrument,
        "timeframe": manifest.timeframe,
        "period": period,
        "first_timestamp": manifest.first_timestamp.isoformat(),
        "last_timestamp": manifest.last_timestamp.isoformat(),
        "row_count": manifest.row_count,
        "file_sha256": manifest.file_sha256,
        "dataset_hash": manifest.dataset_hash,
    }


def _load_public_instruments(instrument_ids: tuple[str, ...]) -> dict[str, object]:
    return {
        instrument_id: load_public_binance_spot_instrument(instrument_id)
        for instrument_id in instrument_ids
    }


def _dataset_for_timeframe(
    *,
    instrument_ids: tuple[str, ...],
    instruments: Mapping[str, object],
    timeframe: str,
    periods: tuple[str, ...],
    data_dir: Path,
) -> tuple[ResearchDataset, tuple[dict[str, object], ...]]:
    bars_by_instrument: dict[str, tuple[object, ...]] = {}
    manifests: list[dict[str, object]] = []
    combined_bars: list[object] = []

    for instrument_id in instrument_ids:
        instrument = instruments[instrument_id]
        raw_symbol = str(getattr(getattr(instrument, "raw_symbol", None), "value", ""))
        if not raw_symbol:
            raise RuntimeError(f"public instrument metadata is missing raw symbol for {instrument_id}")
        collected: list[object] = []
        for period in periods:
            result = _read_verified_public_archive(
                data_dir=data_dir,
                symbol=raw_symbol,
                instrument_id=instrument_id,
                interval=timeframe,
                period=period,
            )
            collected.extend(result.bars)
            manifests.append(_manifest_payload(result, period=period))
        if not collected:
            raise RuntimeError(f"no verified public bars loaded for {instrument_id}")
        bars_by_instrument[instrument_id] = tuple(collected)
        combined_bars.extend(collected)

    dataset = ResearchDataset(
        dataset_hash=dataset_hash_for_bars(combined_bars),
        bars_by_instrument=bars_by_instrument,
        nautilus_instruments=instruments,
        available_data_levels={
            instrument_id: frozenset({"BAR"})
            for instrument_id in instrument_ids
        },
    )
    return dataset, tuple(manifests)


def _public_run_payload(*, family: str, seed: int, timeframe: str, report, manifests) -> dict[str, object]:
    return {
        "family": family,
        "seed": seed,
        "timeframe": timeframe,
        "run_id": report.run_id,
        "generated": report.generated,
        "stored": report.stored,
        "paper_queued": report.paper_queued,
        "resumed": report.resumed,
        "manifests": list(manifests),
        "finalists": [
            {
                "strategy_id": item.strategy_id,
                "genome_hash": item.genome_hash,
                "state": item.state.value,
                "score": item.score,
                "reason": item.reason,
            }
            for item in report.finalists
        ],
    }


def run_research_job(
    plan: ResearchJobPlan,
    *,
    artifact_dir: Path,
    code_hash: str,
    lock_hash: str,
) -> dict[str, object]:
    if not code_hash or not lock_hash:
        raise ValueError("code_hash and lock_hash are required")
    artifact_dir = Path(artifact_dir)
    data_dir = artifact_dir / "public-data"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    periods = _stable_archive_periods(count=plan.archive_months)
    instruments = _load_public_instruments(plan.instruments)
    dataset_cache: dict[str, tuple[ResearchDataset, tuple[dict[str, object], ...]]] = {}
    runs: list[dict[str, object]] = []

    memory = DuckDbResearchMemory(artifact_dir / "research.duckdb")
    try:
        for family in plan.runnable_families:
            for seed in range(plan.seed_start, plan.seed_stop):
                preview = generate_candidate(
                    family=family,
                    instruments=(plan.instruments[0],),
                    seed=seed,
                )
                timeframe = preview.timeframe
                if timeframe not in dataset_cache:
                    dataset_cache[timeframe] = _dataset_for_timeframe(
                        instrument_ids=plan.instruments,
                        instruments=instruments,
                        timeframe=timeframe,
                        periods=periods,
                        data_dir=data_dir,
                    )
                dataset, manifests = dataset_cache[timeframe]
                config = ResearchBrainConfig(
                    families=(family,),
                    instruments=plan.instruments,
                    seed_start=seed,
                    seed_stop=seed + 1,
                    screening_min_return=-1.0,
                    optimization_trials=2,
                    evolution_generations=1,
                    evolution_population=4,
                    validation_budget=len(plan.instruments),
                    paper_queue_cap=1,
                    hidden_fraction=0.20,
                    validation_window=50,
                    trade_size="0.01000",
                    starting_balances=("10 ETH", "10 BTC", "100000 USDT"),
                )
                report = run_research_brain(
                    config,
                    dataset,
                    memory,
                    code_hash=code_hash,
                    lock_hash=lock_hash,
                )
                runs.append(
                    _public_run_payload(
                        family=family,
                        seed=seed,
                        timeframe=timeframe,
                        report=report,
                        manifests=manifests,
                    )
                )
    finally:
        memory.close()

    return {
        "schema_version": 1,
        "source": "binance-public-data",
        "code_hash": code_hash,
        "lock_hash": lock_hash,
        "periods": list(periods),
        "plan": {
            "requested_families": list(plan.requested_families),
            "runnable_families": list(plan.runnable_families),
            "blocked_families": [asdict(item) for item in plan.blocked_families],
            "instruments": list(plan.instruments),
            "seed_start": plan.seed_start,
            "seed_stop": plan.seed_stop,
        },
        "runs": runs,
    }


def main() -> int:
    artifact_dir = Path(os.environ.get("MASTERTRD_RESEARCH_ARTIFACT_DIR", "artifacts/research"))
    code_hash = os.environ.get("GITHUB_SHA") or os.environ.get("MASTERTRD_CODE_HASH")
    if not code_hash:
        raise RuntimeError("GITHUB_SHA or MASTERTRD_CODE_HASH is required")
    lock_path = Path("uv.lock")
    if not lock_path.is_file():
        raise RuntimeError("uv.lock is required")
    lock_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest()

    report = run_research_job(
        default_research_job_plan(),
        artifact_dir=artifact_dir,
        code_hash=code_hash,
        lock_hash=lock_hash,
    )
    report_path = artifact_dir / "research-report.json"
    report_path.write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps({"research_report": str(report_path), "runs": len(report["runs"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
