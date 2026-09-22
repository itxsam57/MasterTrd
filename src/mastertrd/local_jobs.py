from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

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
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def launch_research_job(
    recipe_id: str,
    root: Path,
    *,
    instruments: tuple[str, ...] = (),
    timeframe: str | None = None,
    seed_start: int | None = None,
    seed_stop: int | None = None,
    archive_months: int | None = None,
) -> LocalJobReceipt:
    recipe = strategy_recipe(recipe_id)
    if recipe.readiness is not RecipeReadiness.EXECUTABLE:
        raise ValueError(f"recipe {recipe_id} is not executable: {recipe.blocker}")

    if instruments and len(instruments) < 2:
        raise ValueError("local research requires at least two instruments for transfer validation")
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


def launch_research_matrix(
    recipe_ids: tuple[str, ...],
    root: Path,
    *,
    instruments: tuple[str, ...],
    timeframes: tuple[str, ...],
    seed_start: int,
    seed_stop: int,
    archive_months: int,
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
                )
            )
    if not receipts:
        raise ValueError("research matrix has no compatible recipe/timeframe cells")
    return receipts


def local_result_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for receipt in list_local_jobs(root):
        report_path = Path(receipt.job_dir) / "research" / "research-report.json"
        if not report_path.is_file():
            rows.append(
                {
                    "job_id": receipt.job_id,
                    "recipe_id": receipt.recipe_id,
                    "timeframe": receipt.timeframe,
                    "status": receipt.status,
                    "best_state": None,
                    "best_score": None,
                    "paper_queued": 0,
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
        finalists = [
            finalist
            for run in runs
            if isinstance(run, dict)
            for finalist in run.get("finalists", [])
            if isinstance(finalist, dict)
        ]
        best = max(finalists, key=lambda item: float(item.get("score", float("-inf"))), default=None)
        rows.append(
            {
                "job_id": receipt.job_id,
                "recipe_id": receipt.recipe_id,
                "timeframe": receipt.timeframe,
                "status": receipt.status,
                "best_state": None if best is None else best.get("state"),
                "best_score": None if best is None else best.get("score"),
                "paper_queued": sum(
                    int(run.get("paper_queued", 0))
                    for run in runs
                    if isinstance(run, dict)
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
