from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .app_service import AppService
from .local_jobs import launch_research_job, list_local_jobs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mastertrd", description="Local MasterTrd control plane")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("status", help="Show safe local runtime status")
    subcommands.add_parser("strategies", help="List the full strategy catalog")
    backtest = subcommands.add_parser("backtest", help="Launch an isolated local research job")
    backtest.add_argument("--recipe", required=True)
    backtest.add_argument("--root", default="artifacts/local-jobs")
    jobs = subcommands.add_parser("jobs", help="List local research jobs")
    jobs.add_argument("--root", default="artifacts/local-jobs")
    subcommands.add_parser("app", help="Open the local MasterTrd app")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = AppService()
    if args.command == "status":
        payload = service.snapshot()
    elif args.command == "strategies":
        payload = service.strategy_rows()
    elif args.command == "backtest":
        payload = launch_research_job(args.recipe, Path(args.root)).to_dict()
    elif args.command == "jobs":
        payload = [receipt.to_dict() for receipt in list_local_jobs(Path(args.root))]
    elif args.command == "app":
        app_path = Path(__file__).with_name("local_app.py")
        result = subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.address", "127.0.0.1"], check=False)
        return int(result.returncode)
    else:  # pragma: no cover - argparse enforces valid commands
        raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(payload, sort_keys=True))
    return 0
