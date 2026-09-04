from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
import time

from .paper_session import JsonPaperSessionStore
from .paper_status import paper_status_payload


def _deployment_index(root: Path) -> tuple[str, tuple[dict[str, str], ...]]:
    path = root / "deployment-index.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Oracle PAPER deployment index is unavailable or corrupt") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError("Oracle PAPER deployment index is invalid")
    code_hash = payload.get("code_hash")
    rows = payload.get("candidates")
    if not isinstance(code_hash, str) or not code_hash:
        raise RuntimeError("Oracle PAPER deployment code identity is invalid")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Oracle PAPER deployment candidate set is empty")

    normalized: list[dict[str, str]] = []
    seen_instances: set[str] = set()
    seen_genomes: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RuntimeError("Oracle PAPER deployment candidate row is invalid")
        instance = str(raw.get("instance", ""))
        strategy_id = str(raw.get("strategy_id", ""))
        genome_hash = str(raw.get("genome_hash", ""))
        timeframe = str(raw.get("timeframe", ""))
        row_code_hash = str(raw.get("code_hash", ""))
        if not strategy_id or len(genome_hash) != 64 or not timeframe:
            raise RuntimeError("Oracle PAPER deployment candidate identity is invalid")
        if instance != f"g-{genome_hash[:16]}":
            raise RuntimeError("Oracle PAPER deployment instance identity is invalid")
        if row_code_hash != code_hash:
            raise RuntimeError("Oracle PAPER deployment code identity mismatch")
        if instance in seen_instances or genome_hash in seen_genomes:
            raise RuntimeError("Oracle PAPER deployment contains duplicate identity")
        seen_instances.add(instance)
        seen_genomes.add(genome_hash)
        normalized.append(
            {
                "instance": instance,
                "strategy_id": strategy_id,
                "genome_hash": genome_hash,
                "timeframe": timeframe,
                "code_hash": row_code_hash,
            }
        )
    normalized.sort(key=lambda row: row["instance"])
    return code_hash, tuple(normalized)


def oracle_paper_status_payload(root: Path, *, observed_ns: int) -> dict[str, object]:
    root = Path(root)
    code_hash, rows = _deployment_index(root)
    strategies: list[dict[str, object]] = []
    for row in rows:
        session_path = root / row["genome_hash"] / "paper-session.json"
        if not session_path.is_file():
            strategies.append(
                {
                    **row,
                    "session_present": False,
                    "status": "STARTING",
                }
            )
            continue
        try:
            journal = JsonPaperSessionStore(session_path).load()
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            raise RuntimeError(f"Oracle PAPER session is corrupt for {row['instance']}") from exc
        if (
            journal.strategy_id != row["strategy_id"]
            or journal.genome_hash != row["genome_hash"]
            or journal.code_hash != code_hash
        ):
            raise RuntimeError(f"Oracle PAPER session identity mismatch for {row['instance']}")
        status = paper_status_payload(journal, observed_ns=int(observed_ns))
        status.update(
            {
                "instance": row["instance"],
                "timeframe": row["timeframe"],
                "session_present": True,
                "status": "FINALIZED" if status["finalized"] else "RUNNING",
            }
        )
        strategies.append(status)

    return {
        "schema_version": 1,
        "code_hash": code_hash,
        "strategy_count": len(rows),
        "strategies": strategies,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit sanitized aggregate Oracle PAPER status")
    parser.add_argument("--paper-root", required=True)
    args = parser.parse_args()
    payload = oracle_paper_status_payload(Path(args.paper_root), observed_ns=time.time_ns())
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
