from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .app_service import AppService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mastertrd", description="Local MasterTrd control plane")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("status", help="Show safe local runtime status")
    subcommands.add_parser("strategies", help="List the full strategy catalog")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    service = AppService()
    if args.command == "status":
        payload = service.snapshot()
    elif args.command == "strategies":
        payload = service.strategy_rows()
    else:  # pragma: no cover - argparse enforces valid commands
        raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(payload, sort_keys=True))
    return 0
