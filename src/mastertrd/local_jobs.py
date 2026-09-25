from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from .research_job import research_recipe_coverage
from .source_identity import git_head as _source_git_head
from .strategy_universe import RecipeReadiness, strategy_recipe, strategy_recipe_timeframes


@dataclass(frozen=True, slots=True)
class LocalJobReceipt:
    job_id: str
    kind: str
    recipe_id: str
    status: str
    pid: int | None
    created_at: str
    finished_at: str | None
    job_dir: str
    error: str | None
    instruments: tuple[str, ...] = ()
    timeframe: str | None = None
    seed_start: int | None = None
    seed_stop: int | None = None
    archive_months: int | None = None
    product: str = "SPOT"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _receipt_path(job_dir: Path) -> Path:
    return job_dir / "receipt.json"


def save_receipt(receipt: LocalJobReceipt) -> None:
    path = _receipt_path(Path(receipt.job_dir))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(receipt.to_dict(), sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_receipt(path: Path) -> LocalJobReceipt:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return LocalJobReceipt(**payload)


def _git_head() -> str:
    return _source_git_head()


def launch_research_job(
    recipe_id: str,
    root: Path,
    *,
    instruments: tuple[str, ...] = (),
    timeframe: str | None = None,
    seed_start: int | None = None,
    seed_stop: int | None = None,
    archive_months: int | None = None,
    product: str = "SPOT",
) -> LocalJobReceipt:
    recipe = strategy_recipe(recipe_id)
    if recipe.readiness is not RecipeReadiness.EXECUTABLE:
        raise ValueError(f"recipe {recipe_id} is not executable: {recipe.blocker}")
    normalized_product = str(product).strip().upper()
    coverage = research_recipe_coverage(normalized_product).get(recipe_id, "blocked:unknown_recipe")
    if coverage != "scheduled_public_bar":
        reason = coverage.removeprefix("blocked:")
        raise ValueError(
            f"recipe {recipe_id} is not runnable with the current public Binance {normalized_product} BAR research path: {reason}"
        )

    if normalized_product not in {"SPOT", "USD_M"}:
        raise ValueError("public research product must be SPOT or USD_M")
    minimum_instruments = 4 if recipe.family in {"stat_arb", "portfolio"} else 2
    if instruments and len(instruments) < minimum_instruments:
        raise ValueError(
            f"local {recipe.family} research requires at least {minimum_instruments} "
            "instruments for independent transfer validation"
        )
    if timeframe is not None and timeframe not in strategy_recipe_timeframes(recipe_id):
        raise ValueError(f"timeframe {timeframe} is not supported by recipe {recipe_id}")
    if (seed_start is None) != (seed_stop is None):
        raise ValueError("seed_start and seed_stop must be configured together")
    if seed_start is not None and (seed_stop is None or seed_stop <= seed_start):
        raise ValueError("seed_stop must be greater than seed_start")
    if archive_months is not None and archive_months < 2:
        raise ValueError("archive_months must be at least two")

    root = Path(root)
    job_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    job_dir = root / job_id
    receipt = LocalJobReceipt(
        job_id=job_id,
        kind="RESEARCH",
        recipe_id=recipe_id,
        status="STARTING",
        pid=None,
        created_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        job_dir=str(job_dir),
        error=None,
        instruments=tuple(instruments),
        timeframe=timeframe,
        seed_start=seed_start,
        seed_stop=seed_stop,
        archive_months=archive_months,
        product=normalized_product,
    )
    save_receipt(receipt)

    code_hash = os.environ.get("MASTERTRD_CODE_HASH") or _git_head()
    argv = [
        sys.executable,
        "-m",
        "mastertrd.local_job_worker",
        "--job-dir",
        str(job_dir),
        "--recipe-id",
        recipe_id,
        "--code-hash",
        code_hash,
        "--product",
        normalized_product,
    ]
    if instruments:
        argv.extend(["--instruments", ",".join(instruments)])
    if timeframe is not None:
        argv.extend(["--timeframe", timeframe])
    if seed_start is not None and seed_stop is not None:
        argv.extend(["--seed-start", str(seed_start), "--seed-stop", str(seed_stop)])
    if archive_months is not None:
        argv.extend(["--archive-months", str(archive_months)])
    process = subprocess.Popen(
        argv,
        cwd=Path(__file__).resolve().parents[2],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    receipt = replace(receipt, status="RUNNING", pid=process.pid)
    save_receipt(receipt)
    return receipt


def list_local_jobs(root: Path) -> list[LocalJobReceipt]:
    root = Path(root)
    if not root.exists():
        return []
    receipts = [load_receipt(path) for path in root.glob("*/receipt.json")]
    return sorted(receipts, key=lambda item: item.created_at, reverse=True)


def recommended_archive_months(recipe_id: str) -> int:
    """Return the current promotion-oriented public-history recommendation for a recipe."""
    family = strategy_recipe(recipe_id).family
    if family == "position":
        return 60
    if family == "swing":
        return 26
    if family in {"trend", "volatility"}:
        return 6
    return 2


def _friendly_reason(reason: object) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "No promotion decision was recorded."
    if raw == "required evidence missing":
        return (
            "The candidate completed the run but did not have all evidence required for promotion. "
            "A short history window is a common cause; failed validation stages can also cause this."
        )
    if raw == "paper_queue_cap_reached":
        return (
            "The candidate passed research and hidden validation, but its multi-leg "
            "forward PAPER execution path remains fail-closed."
        )
    marker = "robustness promotion denied:"
    if marker in raw:
        failed = raw.split(marker, 1)[1].replace(",", ", ")
        return f"Initial results did not survive the required robustness checks: {failed}."
    if "public_binance_spot_asset_class_unavailable" in raw or "public_binance_product_asset_class_unavailable" in raw:
        return "This strategy does not match the selected Binance research product."
    if "spot_cash_short_leg_execution_unavailable" in raw:
        return (
            "This multi-leg strategy requires a real short leg; Binance SPOT PAPER uses a cash account, "
            "so run it on USD-M instead."
        )
    if "scheduled_exact_multi_leg_validation_unavailable" in raw:
        return "This is a multi-leg strategy; the current public BAR scheduler does not yet run exact multi-leg validation."
    if "not runnable" in raw:
        return "The selected strategy is not compatible with the current public research path."
    return raw.replace("_", " ")


def _next_action(
    *,
    status: str,
    paper_queued: int,
    reason: object,
    history_months: int | None,
    recommended_months: int,
    product: str = "SPOT",
) -> str:
    if paper_queued > 0:
        return "Review the PAPER finalist and add it to a shared PAPER portfolio."
    if status in {"RUNNING", "STARTING"}:
        return "Wait for the research worker to finish."
    if status == "FAILED":
        return "Choose a strategy marked Runnable now, or add the missing provider/data capability."
    raw = str(reason or "")
    if history_months is not None and history_months < recommended_months:
        return f"Rerun with at least {recommended_months} months before treating this as a serious validation result."
    if "robustness promotion denied:" in raw:
        return "Do not trade this candidate; mutate or retest it until the failed robustness gates pass."
    return "Keep it out of PAPER and test other seeds, timeframes, instruments, or strategy families."


def _result_verdict(*, status: str, paper_queued: int, best: dict[str, object] | None) -> str:
    if status in {"RUNNING", "STARTING"}:
        return "RUNNING"
    if status == "FAILED":
        return "BLOCKED / FAILED"
    if paper_queued > 0:
        return "READY FOR PAPER"
    if best is None:
        return "NO CANDIDATE"
    reason = str(best.get("reason") or "")
    score = float(best.get("score", 0.0))
    if "robustness promotion denied:" in reason and score > 0.0:
        return "PROMISING, NOT ROBUST"
    return "NOT READY"


def launch_research_matrix(
    recipe_ids: tuple[str, ...],
    root: Path,
    *,
    instruments: tuple[str, ...],
    timeframes: tuple[str, ...],
    seed_start: int,
    seed_stop: int,
    archive_months: int,
    product: str = "SPOT",
) -> list[LocalJobReceipt]:
    if not recipe_ids or not timeframes:
        raise ValueError("research matrix requires recipes and timeframes")
    receipts: list[LocalJobReceipt] = []
    for recipe_id in recipe_ids:
        supported = set(strategy_recipe_timeframes(recipe_id))
        for timeframe in timeframes:
            if timeframe not in supported:
                continue
            receipts.append(
                launch_research_job(
                    recipe_id,
                    root,
                    instruments=instruments,
                    timeframe=timeframe,
                    seed_start=seed_start,
                    seed_stop=seed_stop,
                    archive_months=archive_months,
                    product=product,
                )
            )
    if not receipts:
        raise ValueError("research matrix has no compatible recipe/timeframe cells")
    return receipts


def local_result_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for receipt in list_local_jobs(root):
        report_path = Path(receipt.job_dir) / "research" / "research-report.json"
        recommended_months = recommended_archive_months(receipt.recipe_id)
        if not report_path.is_file():
            explanation = _friendly_reason(receipt.error)
            rows.append(
                {
                    "job_id": receipt.job_id,
                    "recipe_id": receipt.recipe_id,
                    "product": receipt.product,
                    "timeframe": receipt.timeframe,
                    "status": receipt.status,
                    "verdict": _result_verdict(status=receipt.status, paper_queued=0, best=None),
                    "best_state": None,
                    "best_score": None,
                    "best_strategy_id": None,
                    "best_reason": receipt.error,
                    "explanation": explanation,
                    "next_action": _next_action(
                        status=receipt.status,
                        paper_queued=0,
                        reason=receipt.error,
                        history_months=receipt.archive_months,
                        recommended_months=recommended_months,
                        product=receipt.product,
                    ),
                    "candidate_count": 0,
                    "paper_queued": 0,
                    "history_months": receipt.archive_months,
                    "recommended_history_months": recommended_months,
                    "validation_depth": (
                        "QUICK / INCOMPLETE"
                        if receipt.archive_months is not None and receipt.archive_months < recommended_months
                        else "STANDARD WINDOW"
                    ),
                    "report": None,
                    "duckdb": str(Path(receipt.job_dir) / "research" / "research.duckdb"),
                    "stdout": str(Path(receipt.job_dir) / "stdout.log"),
                    "stderr": str(Path(receipt.job_dir) / "stderr.log"),
                    "error": receipt.error,
                }
            )
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {}
        runs = report.get("runs", []) if isinstance(report, dict) else []
        finalist_pairs = [
            (finalist, run)
            for run in runs
            if isinstance(run, dict)
            for finalist in run.get("finalists", [])
            if isinstance(finalist, dict)
        ]
        best_pair = max(
            finalist_pairs,
            key=lambda item: float(item[0].get("score", float("-inf"))),
            default=None,
        )
        best = None if best_pair is None else best_pair[0]
        best_run = None if best_pair is None else best_pair[1]
        finalists = [item[0] for item in finalist_pairs]
        paper_queued = sum(
            int(run.get("paper_queued", 0))
            for run in runs
            if isinstance(run, dict)
        )
        plan = report.get("plan", {}) if isinstance(report, dict) else {}
        report_history = plan.get("archive_months") if isinstance(plan, dict) else None
        history_months = (
            int(report_history)
            if isinstance(report_history, int)
            else receipt.archive_months
        )
        best_reason = None if best is None else best.get("reason")
        rows.append(
            {
                "job_id": receipt.job_id,
                "recipe_id": receipt.recipe_id,
                "product": receipt.product,
                "timeframe": (
                    receipt.timeframe
                    if receipt.timeframe is not None
                    else (None if best_run is None else best_run.get("timeframe"))
                ),
                "best_seed": None if best_run is None else best_run.get("seed"),
                "status": receipt.status,
                "verdict": _result_verdict(status=receipt.status, paper_queued=paper_queued, best=best),
                "best_state": None if best is None else best.get("state"),
                "best_score": None if best is None else best.get("score"),
                "best_strategy_id": None if best is None else best.get("strategy_id"),
                "best_reason": best_reason,
                "explanation": _friendly_reason(best_reason if best is not None else receipt.error),
                "next_action": _next_action(
                    status=receipt.status,
                    paper_queued=paper_queued,
                    reason=best_reason if best is not None else receipt.error,
                    history_months=history_months,
                    recommended_months=recommended_months,
                    product=receipt.product,
                ),
                "candidate_count": len(finalists),
                "paper_queued": paper_queued,
                "history_months": history_months,
                "recommended_history_months": recommended_months,
                "validation_depth": (
                    "QUICK / INCOMPLETE"
                    if history_months is not None and history_months < recommended_months
                    else "STANDARD WINDOW"
                ),
                "report": str(report_path),
                "duckdb": str(Path(receipt.job_dir) / "research" / "research.duckdb"),
                "stdout": str(Path(receipt.job_dir) / "stdout.log"),
                "stderr": str(Path(receipt.job_dir) / "stderr.log"),
                "error": receipt.error,
            }
        )
    return rows

def local_paper_candidates(root: Path) -> list[dict[str, object]]:
    candidates: dict[str, dict[str, object]] = {}
    for receipt in list_local_jobs(root):
        report_path = Path(receipt.job_dir) / "research" / "research-report.json"
        if not report_path.is_file():
            continue
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for run in report.get("runs", []) if isinstance(report, dict) else []:
            if not isinstance(run, dict):
                continue
            for manifest in run.get("paper_candidates", []):
                if not isinstance(manifest, dict):
                    continue
                genome_hash = manifest.get("genome_hash")
                if not isinstance(genome_hash, str) or not genome_hash:
                    continue
                candidates[genome_hash] = {
                    "job_id": receipt.job_id,
                    "product": receipt.product,
                    "recipe_id": run.get("recipe_id") or receipt.recipe_id,
                    "timeframe": run.get("timeframe") or receipt.timeframe,
                    "strategy_id": manifest.get("strategy_id"),
                    "genome_hash": genome_hash,
                    "code_hash": manifest.get("code_hash"),
                    "lock_hash": manifest.get("lock_hash"),
                    "manifest": manifest,
                }
    return sorted(
        candidates.values(),
        key=lambda item: (
            str(item.get("recipe_id") or ""),
            str(item.get("strategy_id") or ""),
        ),
    )
