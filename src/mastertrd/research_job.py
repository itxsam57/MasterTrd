from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .advanced_validation import AdvancedValidationPolicy
from .asset_transfer import AssetTransferPolicy
from .contracts import StrategyState
from .data.archive import ArchiveReadResult, dataset_hash_for_bars, read_binance_archive
from .data.binance_public import binance_kline_url
from .genome import StrategyGenome
from .hidden_gate import HiddenGatePolicy
from .memory_duckdb import DuckDbResearchMemory
from .nautilus_paper import load_public_binance_spot_instrument
from .research.generator import generate_candidate
from .research_brain import ResearchBrainConfig, ResearchDataset, run_research_brain
from .robustness import RobustnessPolicy
from .strategy_families import DataLevel, FAMILIES, family_spec
from .strategy_universe import (
    AssetClass,
    RecipeReadiness,
    STRATEGY_RECIPES,
    strategy_recipe,
)


class ResearchProfile(str, Enum):
    SMOKE = "smoke"
    PRODUCTION = "production"


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
    runnable_recipe_ids: tuple[str, ...] = ()

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
        if len(set(self.runnable_recipe_ids)) != len(self.runnable_recipe_ids):
            raise ValueError("runnable_recipe_ids must be unique")
        for recipe_id in self.runnable_recipe_ids:
            recipe = strategy_recipe(recipe_id)
            if recipe.readiness is not RecipeReadiness.EXECUTABLE:
                raise ValueError("scheduled recipe must be executable")
            if recipe.family not in self.runnable_families:
                raise ValueError("scheduled recipe family must be runnable")
            if AssetClass.CRYPTO not in recipe.asset_classes:
                raise ValueError("scheduled public recipe must support crypto")
            spec = family_spec(recipe.family)
            if spec.min_data_level is not DataLevel.BAR:
                raise ValueError("scheduled public recipe must use BAR data")
            if spec.max_instruments != 1:
                raise ValueError("scheduled public recipe must be single-leg")


def scheduled_public_recipe_ids() -> tuple[str, ...]:
    """Return every executable recipe that the current public BAR job can test honestly.

    This is intentionally capability-derived rather than a hand-maintained shortlist:
    an admitted recipe must be executable today, support crypto, require only BAR data,
    and be single-leg. Everything else remains visible through
    ``research_recipe_coverage`` with an explicit blocker.
    """

    return tuple(
        recipe.recipe_id
        for recipe in STRATEGY_RECIPES
        if recipe.readiness is RecipeReadiness.EXECUTABLE
        and AssetClass.CRYPTO in recipe.asset_classes
        and family_spec(recipe.family).min_data_level is DataLevel.BAR
        and family_spec(recipe.family).max_instruments == 1
    )


def research_recipe_coverage() -> dict[str, str]:
    """Classify every planned recipe as scheduled now or explicitly blocked."""

    scheduled = frozenset(scheduled_public_recipe_ids())
    coverage: dict[str, str] = {}
    for recipe in STRATEGY_RECIPES:
        if recipe.recipe_id in scheduled:
            coverage[recipe.recipe_id] = "scheduled_public_bar"
            continue
        spec = family_spec(recipe.family)
        if recipe.readiness is not RecipeReadiness.EXECUTABLE:
            reason = recipe.blocker or f"{recipe.readiness.value.lower()}_requirements_unsatisfied"
        elif AssetClass.CRYPTO not in recipe.asset_classes:
            reason = "public_binance_spot_asset_class_unavailable"
        elif spec.min_data_level is not DataLevel.BAR:
            reason = f"qualifying_public_{spec.min_data_level.value.lower()}_data_unavailable"
        elif spec.max_instruments != 1:
            reason = "scheduled_exact_multi_leg_validation_unavailable"
        else:
            reason = "scheduled_public_provider_contract_unavailable"
        coverage[recipe.recipe_id] = f"blocked:{reason}"
    return coverage


def _default_runnable_recipe_ids(runnable_families: tuple[str, ...]) -> tuple[str, ...]:
    selected = tuple(
        recipe_id
        for recipe_id in scheduled_public_recipe_ids()
        if strategy_recipe(recipe_id).family in runnable_families
    )
    if not selected:
        raise RuntimeError("scheduled research has no compatible executable recipes")
    return selected


def _archive_months_for_recipe(recipe_id: str) -> int:
    """Give slow families enough stable monthly data for their generated lookbacks."""

    family = strategy_recipe(recipe_id).family
    if family == "position":
        return 18
    if family == "swing":
        return 8
    return 2


def default_research_job_plan() -> ResearchJobPlan:
    requested = tuple(FAMILIES)
    scheduled = scheduled_public_recipe_ids()
    runnable = tuple(
        family
        for family in requested
        if any(strategy_recipe(recipe_id).family == family for recipe_id in scheduled)
    )
    reasons = {
        "stat_arb": "scheduled_exact_multi_leg_validation_unavailable",
        "funding_basis": "scheduled_exact_multi_leg_validation_unavailable",
        "delta_neutral": "scheduled_exact_multi_leg_validation_unavailable",
        "portfolio": "scheduled_exact_multi_leg_validation_unavailable",
        "options": "qualifying_public_option_data_unavailable",
        "scalping": "qualifying_public_tick_data_unavailable",
        "grid": "qualifying_public_tick_data_unavailable",
        "market_making": "qualifying_public_l2_data_unavailable",
        "order_book": "qualifying_public_l2_data_unavailable",
        "cross_venue_arb": "qualifying_public_tick_data_unavailable",
    }
    blocked = tuple(
        ResearchJobBlocker(
            family=family,
            reason=reasons.get(family, "scheduled_public_recipe_unavailable"),
        )
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
        runnable_recipe_ids=_default_runnable_recipe_ids(runnable),
    )


def research_job_plan_for_recipe(recipe_id: str) -> ResearchJobPlan:
    """Return one fail-closed shard of the complete autonomous public schedule."""

    base = default_research_job_plan()
    if recipe_id not in base.runnable_recipe_ids:
        disposition = research_recipe_coverage().get(recipe_id, "blocked:unknown_recipe")
        raise ValueError(f"{recipe_id!r} is not runnable in public BAR research: {disposition}")
    recipe = strategy_recipe(recipe_id)
    return ResearchJobPlan(
        requested_families=base.requested_families,
        runnable_families=(recipe.family,),
        blocked_families=base.blocked_families,
        instruments=base.instruments,
        seed_start=base.seed_start,
        seed_stop=base.seed_stop,
        archive_months=_archive_months_for_recipe(recipe_id),
        runnable_recipe_ids=(recipe_id,),
    )


def research_brain_config_for_run(
    *,
    plan: ResearchJobPlan,
    family: str,
    seed: int,
    recipe_id: str | None,
    profile: ResearchProfile = ResearchProfile.SMOKE,
) -> ResearchBrainConfig:
    """Build one explicit research policy so smoke and candidate production cannot drift."""
    common = dict(
        families=(family,),
        instruments=plan.instruments,
        seed_start=seed,
        seed_stop=seed + 1,
        validation_budget=len(plan.instruments),
        paper_queue_cap=1,
        hidden_fraction=0.20,
        validation_window=50,
        trade_size="0.01000",
        starting_balances=("10 ETH", "10 BTC", "100000 USDT"),
        recipe_ids=(recipe_id,) if recipe_id is not None else (),
    )
    if profile is ResearchProfile.SMOKE:
        return ResearchBrainConfig(
            screening_min_return=-1.0,
            optimization_trials=2,
            evolution_generations=1,
            evolution_population=4,
            **common,
        )
    if profile is not ResearchProfile.PRODUCTION:
        raise ValueError(f"unsupported research profile: {profile!r}")
    return ResearchBrainConfig(
        screening_min_return=0.0,
        optimization_trials=24,
        evolution_generations=8,
        evolution_population=16,
        fees=0.001,
        slippage=0.0005,
        stressed_fees=0.002,
        stressed_slippage=0.001,
        robustness_policy=RobustnessPolicy(
            min_trades_per_slice=5,
            min_profitable_slice_ratio=0.50,
            max_drawdown=0.25,
            min_stressed_return=0.0,
            max_return_degradation=0.50,
            min_stable_neighbor_ratio=0.50,
        ),
        advanced_policy=AdvancedValidationPolicy(
            min_evaluations=1,
            min_trades_per_evaluation=5,
            min_positive_ratio=1.0,
            max_drawdown=0.25,
            min_monte_carlo_survival_ratio=1.0,
            max_monte_carlo_loss=-0.10,
        ),
        asset_transfer_policy=AssetTransferPolicy(
            min_transfer_assets=1,
            min_trades_per_asset=5,
            min_pass_ratio=1.0,
            min_total_return=0.0,
            max_drawdown=0.25,
        ),
        hidden_policy=HiddenGatePolicy(
            min_trades_per_evaluation=5,
            min_total_return=0.0,
            max_drawdown=0.25,
            min_regime_pass_ratio=0.67,
        ),
        **common,
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


def _is_retryable_public_data_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 429 or 500 <= exc.code <= 599
    return isinstance(exc, (URLError, TimeoutError, ConnectionError))


def _retry_sleep_seconds(attempt: int) -> float:
    return float(2 ** (attempt - 1))


def _read_url_text_with_retry(
    url: str,
    *,
    timeout: int,
    urlopen_fn=None,
    sleep_fn=None,
    max_attempts: int = 4,
) -> str:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    opener = urlopen if urlopen_fn is None else urlopen_fn
    sleeper = time.sleep if sleep_fn is None else sleep_fn
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(url, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except Exception as exc:
            if not _is_retryable_public_data_error(exc) or attempt >= max_attempts:
                raise
            sleeper(_retry_sleep_seconds(attempt))
    raise RuntimeError("public data retry loop ended unexpectedly")


def _download(
    url: str,
    destination: Path,
    *,
    urlopen_fn=None,
    sleep_fn=None,
    max_attempts: int = 4,
) -> None:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    opener = urlopen if urlopen_fn is None else urlopen_fn
    sleeper = time.sleep if sleep_fn is None else sleep_fn
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.part")

    for attempt in range(1, max_attempts + 1):
        try:
            partial.unlink(missing_ok=True)
            with opener(url, timeout=60) as response, partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, destination)
            return
        except Exception as exc:
            partial.unlink(missing_ok=True)
            if not _is_retryable_public_data_error(exc) or attempt >= max_attempts:
                raise
            sleeper(_retry_sleep_seconds(attempt))
    raise RuntimeError("public archive retry loop ended unexpectedly")


def _read_verified_public_archive(
    *,
    data_dir: Path,
    symbol: str,
    instrument_id: str,
    interval: str,
    period: str,
) -> ArchiveReadResult:
    raw_symbol = str(symbol).strip().upper()
    qualified_instrument = str(instrument_id).strip().upper()
    if qualified_instrument != f"{raw_symbol}.BINANCE":
        raise ValueError("public archive instrument ID does not match Binance symbol")
    url = binance_kline_url(
        market="spot",
        symbol=raw_symbol,
        interval=interval,
        period=period,
    )
    checksum_url = f"{url}.CHECKSUM"
    checksum_text = _read_url_text_with_retry(checksum_url, timeout=30)
    expected_sha256 = _checksum_from_response(checksum_text)
    archive_path = data_dir / url.rsplit("/", 1)[-1]
    _download(url, archive_path)
    return read_binance_archive(
        archive_path,
        expected_sha256=expected_sha256,
        symbol=raw_symbol,
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


def _paper_candidate_manifests(
    *,
    report,
    memory: DuckDbResearchMemory,
    code_hash: str,
    dataset_hash: str,
    lock_hash: str,
    recipe_id: str | None,
) -> list[dict[str, object]]:
    paper_finalists = [
        finalist
        for finalist in report.finalists
        if finalist.state == StrategyState.PAPER
    ]
    if not paper_finalists:
        return []

    robustness = memory.get_stage(report.run_id, "hidden_robustness_stress")
    if robustness is None or not isinstance(robustness.artifact, Mapping):
        raise RuntimeError("queued PAPER candidate is missing robustness provenance")
    raw_outcomes = robustness.artifact.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise RuntimeError("queued PAPER candidate robustness provenance is invalid")

    candidates_by_hash: dict[str, StrategyGenome] = {}
    for outcome in raw_outcomes:
        if not isinstance(outcome, Mapping):
            continue
        raw_genome = outcome.get("genome")
        if not isinstance(raw_genome, Mapping):
            continue
        try:
            candidate = StrategyGenome(**dict(raw_genome))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("queued PAPER candidate genome provenance is invalid") from exc
        candidates_by_hash[candidate.genome_hash] = candidate

    manifests: list[dict[str, object]] = []
    for finalist in paper_finalists:
        candidate = candidates_by_hash.get(finalist.genome_hash)
        if candidate is None or candidate.strategy_id != finalist.strategy_id:
            raise RuntimeError("queued PAPER candidate genome could not be recovered")
        manifests.append(
            {
                "candidate": candidate.canonical_payload(),
                "strategy_id": candidate.strategy_id,
                "genome_hash": candidate.genome_hash,
                "code_hash": code_hash,
                "dataset_hash": dataset_hash,
                "lock_hash": lock_hash,
                "recipe_id": recipe_id,
            }
        )
    return manifests


def _public_run_payload(
    *,
    family: str,
    seed: int,
    timeframe: str,
    report,
    manifests,
    recipe_id: str | None = None,
    paper_candidates=(),
) -> dict[str, object]:
    return {
        "family": family,
        "recipe_id": recipe_id,
        "seed": seed,
        "timeframe": timeframe,
        "run_id": report.run_id,
        "generated": report.generated,
        "stored": report.stored,
        "paper_queued": report.paper_queued,
        "resumed": report.resumed,
        "manifests": list(manifests),
        "paper_candidates": list(paper_candidates),
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
    profile: ResearchProfile = ResearchProfile.SMOKE,
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

    if plan.runnable_recipe_ids:
        schedule = tuple(
            (strategy_recipe(recipe_id).family, recipe_id)
            for recipe_id in plan.runnable_recipe_ids
        )
    else:
        schedule = tuple((family, None) for family in plan.runnable_families)

    memory = DuckDbResearchMemory(artifact_dir / "research.duckdb")
    try:
        for family, recipe_id in schedule:
            for seed in range(plan.seed_start, plan.seed_stop):
                preview = generate_candidate(
                    family=family,
                    instruments=(plan.instruments[0],),
                    seed=seed,
                    recipe_id=recipe_id,
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
                config = research_brain_config_for_run(
                    plan=plan,
                    family=family,
                    seed=seed,
                    recipe_id=recipe_id,
                    profile=profile,
                )
                report = run_research_brain(
                    config,
                    dataset,
                    memory,
                    code_hash=code_hash,
                    lock_hash=lock_hash,
                )
                paper_candidates = _paper_candidate_manifests(
                    report=report,
                    memory=memory,
                    code_hash=code_hash,
                    dataset_hash=dataset.dataset_hash,
                    lock_hash=lock_hash,
                    recipe_id=recipe_id,
                )
                runs.append(
                    _public_run_payload(
                        family=family,
                        recipe_id=recipe_id,
                        seed=seed,
                        timeframe=timeframe,
                        report=report,
                        manifests=manifests,
                        paper_candidates=paper_candidates,
                    )
                )
    finally:
        memory.close()

    return {
        "schema_version": 1,
        "research_profile": profile.value,
        "source": "binance-public-data",
        "code_hash": code_hash,
        "lock_hash": lock_hash,
        "periods": list(periods),
        "recipe_coverage": research_recipe_coverage(),
        "plan": {
            "requested_families": list(plan.requested_families),
            "runnable_families": list(plan.runnable_families),
            "runnable_recipe_ids": list(plan.runnable_recipe_ids),
            "blocked_families": [asdict(item) for item in plan.blocked_families],
            "instruments": list(plan.instruments),
            "seed_start": plan.seed_start,
            "seed_stop": plan.seed_stop,
            "archive_months": plan.archive_months,
        },
        "runs": runs,
    }


def main() -> int:
    artifact_dir = Path(os.environ.get("MASTERTRD_RESEARCH_ARTIFACT_DIR", "artifacts/research"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    code_hash = os.environ.get("GITHUB_SHA") or os.environ.get("MASTERTRD_CODE_HASH")
    if not code_hash:
        raise RuntimeError("GITHUB_SHA or MASTERTRD_CODE_HASH is required")
    lock_path = Path("uv.lock")
    if not lock_path.is_file():
        raise RuntimeError("uv.lock is required")
    lock_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest()

    recipe_id = os.environ.get("MASTERTRD_RESEARCH_RECIPE_ID", "").strip()
    raw_profile = os.environ.get("MASTERTRD_RESEARCH_PROFILE", ResearchProfile.SMOKE.value).strip().lower()
    try:
        profile = ResearchProfile(raw_profile)
    except ValueError as exc:
        raise RuntimeError(f"invalid MASTERTRD_RESEARCH_PROFILE: {raw_profile!r}") from exc
    plan = research_job_plan_for_recipe(recipe_id) if recipe_id else default_research_job_plan()
    report = run_research_job(
        plan,
        artifact_dir=artifact_dir,
        code_hash=code_hash,
        lock_hash=lock_hash,
        profile=profile,
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