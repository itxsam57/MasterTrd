from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .genome import StrategyGenome


@dataclass(frozen=True, slots=True)
class DurableResearchRecord:
    experiment_id: str
    genome_hash: str
    strategy_id: str
    status: str
    engine: str
    score: float
    reason: str
    metadata: Mapping[str, Any]
    created_at: str


class DuckDbResearchMemory:
    def __init__(self, path: str | Path) -> None:
        import duckdb

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self.path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_records (
                experiment_id VARCHAR PRIMARY KEY,
                genome_hash VARCHAR NOT NULL,
                strategy_id VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                engine VARCHAR NOT NULL,
                score DOUBLE NOT NULL,
                reason VARCHAR NOT NULL,
                metadata_json VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL
            )
            """
        )

    @staticmethod
    def _row_to_record(row: tuple[Any, ...]) -> DurableResearchRecord:
        return DurableResearchRecord(
            experiment_id=str(row[0]),
            genome_hash=str(row[1]),
            strategy_id=str(row[2]),
            status=str(row[3]),
            engine=str(row[4]),
            score=float(row[5]),
            reason=str(row[6]),
            metadata=json.loads(str(row[7])),
            created_at=str(row[8]),
        )

    def append(
        self,
        *,
        experiment_id: str,
        genome: StrategyGenome,
        status: str,
        engine: str,
        score: float,
        reason: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> DurableResearchRecord:
        if not experiment_id:
            raise ValueError("experiment_id is required")
        if not status:
            raise ValueError("status is required")
        if not engine:
            raise ValueError("engine is required")
        numeric_score = float(score)
        if not isfinite(numeric_score):
            raise ValueError("score must be finite")

        metadata_value = dict(metadata or {})
        metadata_json = json.dumps(
            metadata_value,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = self.get(experiment_id)
        if existing is not None:
            same = (
                existing.genome_hash == genome.genome_hash
                and existing.strategy_id == genome.strategy_id
                and existing.status == status
                and existing.engine == engine
                and existing.score == numeric_score
                and existing.reason == reason
                and dict(existing.metadata) == metadata_value
            )
            if not same:
                raise ValueError("experiment_id already exists with different result")
            return existing

        created_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO research_records (
                experiment_id, genome_hash, strategy_id, status, engine,
                score, reason, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                experiment_id,
                genome.genome_hash,
                genome.strategy_id,
                status,
                engine,
                numeric_score,
                reason,
                metadata_json,
                created_at,
            ],
        )
        record = self.get(experiment_id)
        if record is None:
            raise RuntimeError("research record insert could not be read back")
        return record

    def get(self, experiment_id: str) -> DurableResearchRecord | None:
        row = self._conn.execute(
            """
            SELECT experiment_id, genome_hash, strategy_id, status, engine,
                   score, reason, metadata_json, created_at
            FROM research_records
            WHERE experiment_id = ?
            """,
            [experiment_id],
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM research_records").fetchone()
        return int(row[0])

    def by_genome(self, genome_hash: str) -> list[DurableResearchRecord]:
        rows = self._conn.execute(
            """
            SELECT experiment_id, genome_hash, strategy_id, status, engine,
                   score, reason, metadata_json, created_at
            FROM research_records
            WHERE genome_hash = ?
            ORDER BY created_at, experiment_id
            """,
            [genome_hash],
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def by_status(self, status: str) -> list[DurableResearchRecord]:
        rows = self._conn.execute(
            """
            SELECT experiment_id, genome_hash, strategy_id, status, engine,
                   score, reason, metadata_json, created_at
            FROM research_records
            WHERE status = ?
            ORDER BY created_at, experiment_id
            """,
            [status],
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def export_parquet(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        escaped_path = str(target).replace("'", "''")
        self._conn.execute(
            f"""
            COPY (
                SELECT experiment_id, genome_hash, strategy_id, status, engine,
                       score, reason, metadata_json, created_at
                FROM research_records
                ORDER BY created_at, experiment_id
            ) TO '{escaped_path}' (FORMAT PARQUET)
            """
        )

    def close(self) -> None:
        self._conn.close()
