from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import traceback

from . import research_job
from .local_jobs import load_receipt, save_receipt


def run_research_worker(
    job_dir: Path,
    *,
    recipe_id: str,
    code_hash: str,
    instruments: str | None = None,
    timeframe: str | None = None,
    seed_start: int | None = None,
    seed_stop: int | None = None,
    archive_months: int | None = None,
) -> int:
    job_dir = Path(job_dir)
    receipt_path = job_dir / "receipt.json"
    receipt = load_receipt(receipt_path)
    artifact_dir = job_dir / "research"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    env_keys = (
        "MASTERTRD_RESEARCH_RECIPE_ID",
        "MASTERTRD_RESEARCH_ARTIFACT_DIR",
        "MASTERTRD_CODE_HASH",
        "MASTERTRD_RESEARCH_INSTRUMENTS",
        "MASTERTRD_RESEARCH_TIMEFRAMES",
        "MASTERTRD_RESEARCH_SEED_START",
        "MASTERTRD_RESEARCH_SEED_STOP",
        "MASTERTRD_RESEARCH_ARCHIVE_MONTHS",
    )
    previous_env = {key: os.environ.get(key) for key in env_keys}
    os.environ["MASTERTRD_RESEARCH_RECIPE_ID"] = recipe_id
    os.environ["MASTERTRD_RESEARCH_ARTIFACT_DIR"] = str(artifact_dir)
    os.environ["MASTERTRD_CODE_HASH"] = code_hash

    if instruments:
        os.environ["MASTERTRD_RESEARCH_INSTRUMENTS"] = instruments
    if timeframe:
        os.environ["MASTERTRD_RESEARCH_TIMEFRAMES"] = timeframe
    if seed_start is not None and seed_stop is not None:
        os.environ["MASTERTRD_RESEARCH_SEED_START"] = str(seed_start)
        os.environ["MASTERTRD_RESEARCH_SEED_STOP"] = str(seed_stop)
    if archive_months is not None:
        os.environ["MASTERTRD_RESEARCH_ARCHIVE_MONTHS"] = str(archive_months)

    stdout_path = job_dir / "stdout.log"
    stderr_path = job_dir / "stderr.log"
    try:
        try:
            with stdout_path.open("a", encoding="utf-8") as stdout, stderr_path.open("a", encoding="utf-8") as stderr:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = int(research_job.main())
            status = "SUCCEEDED" if exit_code == 0 else "FAILED"
            error = None if exit_code == 0 else f"exit_code={exit_code}"
        except Exception as exc:  # worker boundary must preserve failure evidence
            with stderr_path.open("a", encoding="utf-8") as stderr:
                traceback.print_exc(file=stderr)
            status = "FAILED"
            error = f"{type(exc).__name__}: {exc}"
            exit_code = 1

        save_receipt(
            replace(
                receipt,
                status=status,
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=error,
            )
        )
        return exit_code
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one isolated local MasterTrd research job")
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--recipe-id", required=True)
    parser.add_argument("--code-hash", required=True)
    parser.add_argument("--instruments")
    parser.add_argument("--timeframe")
    parser.add_argument("--seed-start", type=int)
    parser.add_argument("--seed-stop", type=int)
    parser.add_argument("--archive-months", type=int)
    args = parser.parse_args()
    return run_research_worker(
        Path(args.job_dir),
        recipe_id=args.recipe_id,
        code_hash=args.code_hash,
        instruments=args.instruments,
        timeframe=args.timeframe,
        seed_start=args.seed_start,
        seed_stop=args.seed_stop,
        archive_months=args.archive_months,
    )


if __name__ == "__main__":
    raise SystemExit(main())
