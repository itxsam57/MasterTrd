from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from .strategy_universe import RecipeReadiness, strategy_recipe


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


def launch_research_job(recipe_id: str, root: Path) -> LocalJobReceipt:
    recipe = strategy_recipe(recipe_id)
    if recipe.readiness is not RecipeReadiness.EXECUTABLE:
        raise ValueError(f"recipe {recipe_id} is not executable: {recipe.blocker}")

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
