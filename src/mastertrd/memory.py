from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from .genome import StrategyGenome


@dataclass(frozen=True, slots=True)
class ResearchRecord:
    genome_hash: str
    status: str
    engine: str
    score: float
    reason: str
    metadata: Mapping[str, Any]
    created_at: str


class JsonlResearchMemory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(
        self,
        genome: StrategyGenome,
        *,
        status: str,
        engine: str,
        score: float,
        reason: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ResearchRecord:
        record = ResearchRecord(
            genome_hash=genome.genome_hash,
            status=status,
            engine=engine,
            score=float(score),
            reason=reason,
            metadata=dict(metadata or {}),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) + "\n")
        return record

    def read_all(self) -> list[ResearchRecord]:
        if not self.path.exists():
            return []
        result: list[ResearchRecord] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                payload = json.loads(line)
                result.append(ResearchRecord(**payload))
        return result
