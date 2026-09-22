from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .trading_service import TradingService
from .local_jobs import launch_research_job, list_local_jobs
from .local_scheduler import run_scheduler


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
    subcommands.add_parser("trading", help="Run the persistent local trading worker")
    config = subcommands.add_parser("config", help="Save safe local runtime settings")
    config.add_argument("--mode", choices=("PAPER", "DEMO", "TESTNET"), required=True)
    config.add_argument("--product", choices=("SPOT", "USD_M", "COIN_M"), default="SPOT")
    scheduler = subcommands.add_parser("scheduler", help="Run local recurring checks and research")
    scheduler.add_argument("--poll-seconds", type=float, default=60.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = TradingService()
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
    elif args.command == "scheduler":
        run_scheduler(poll_seconds=args.poll_seconds)
        return 0
    elif args.command == "trading":
        service.run_forever(
            heartbeat=lambda state: print(f"MasterTrd heartbeat: {state}", file=sys.stderr, flush=True)
        )
        return 0
    elif args.command == "config":
        path = service.save_local_settings(mode=args.mode, product=args.product)
        payload = {"config": str(path), "mode": args.mode, "product": args.product}
    else:  # pragma: no cover - argparse enforces valid commands
        raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(payload, sort_keys=True))
    return 0
