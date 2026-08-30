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


@dataclass(frozen=True, slots=True)
class ResearchStageReceipt:
    run_id: str
    stage: str
    artifact: Mapping[str, Any]
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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_stage_receipts (
                run_id VARCHAR NOT NULL,
                stage VARCHAR NOT NULL,
                artifact_json VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL,
                PRIMARY KEY (run_id, stage)
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

    @staticmethod
    def _row_to_stage(row: tuple[Any, ...]) -> ResearchStageReceipt:
        return ResearchStageReceipt(
            run_id=str(row[0]),
            stage=str(row[1]),
            artifact=json.loads(str(row[2])),
            created_at=str(row[3]),
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

    def record_stage(
        self,
        *,
        run_id: str,
        stage: str,
        artifact: Mapping[str, Any],
    ) -> ResearchStageReceipt:
        if not run_id:
            raise ValueError("run_id is required")
        if not stage:
            raise ValueError("stage is required")
        artifact_value = dict(artifact)
        artifact_json = json.dumps(
            artifact_value,
            sort_keys=True,
            separators=(",", ":"),
        )
        existing = self.get_stage(run_id, stage)
        if existing is not None:
            if dict(existing.artifact) != artifact_value:
                raise ValueError("stage receipt already exists with different artifact")
            return existing

        created_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO research_stage_receipts (run_id, stage, artifact_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [run_id, stage, artifact_json, created_at],
        )
        receipt = self.get_stage(run_id, stage)
        if receipt is None:
            raise RuntimeError("stage receipt insert could not be read back")
        return receipt

    def get_stage(self, run_id: str, stage: str) -> ResearchStageReceipt | None:
        row = self._conn.execute(
            """
            SELECT run_id, stage, artifact_json, created_at
            FROM research_stage_receipts
            WHERE run_id = ? AND stage = ?
            """,
            [run_id, stage],
        ).fetchone()
        return None if row is None else self._row_to_stage(row)

    def stage_receipts(self, run_id: str) -> list[ResearchStageReceipt]:
        rows = self._conn.execute(
            """
            SELECT run_id, stage, artifact_json, created_at
            FROM research_stage_receipts
            WHERE run_id = ?
            ORDER BY created_at, stage
            """,
            [run_id],
        ).fetchall()
        return [self._row_to_stage(row) for row in rows]

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
