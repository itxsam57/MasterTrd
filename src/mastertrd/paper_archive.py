from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from .paper_forward import PaperForwardReport


class JsonPaperReportArchive:
    VERSION = 1

    def __init__(self, path: str | Path):
        self._path = Path(path)

    @staticmethod
    def _canonical_reports(reports: Iterable[PaperForwardReport]) -> list[dict[str, object]]:
        return [asdict(report) for report in reports]

    @staticmethod
    def _hash_raw_reports(reports: list[object]) -> str:
        encoded = json.dumps(
            reports,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _hash_reports(cls, reports: Iterable[PaperForwardReport]) -> str:
        return cls._hash_raw_reports(list(cls._canonical_reports(reports)))

    @staticmethod
    def _validate_collection(reports: list[PaperForwardReport]) -> None:
        session_ids: set[str] = set()
        reference: PaperForwardReport | None = None
        for report in reports:
            if not report.provenance_verified:
                raise ValueError("paper report archive accepts only verified reports")
            if not report.code_hash or not report.session_event_hash:
                raise ValueError("verified paper reports require provenance identity")
            if report.session_id in session_ids:
                raise ValueError("paper report session_id values must be unique")
            session_ids.add(report.session_id)

            if reference is None:
                reference = report
                continue
            if report.strategy_id != reference.strategy_id:
                raise ValueError("strategy_id must match across archived paper reports")
            if report.genome_hash != reference.genome_hash:
                raise ValueError("genome_hash must match across archived paper reports")
            if report.code_hash != reference.code_hash:
                raise ValueError("code_hash must match across archived paper reports")
            if report.engine != reference.engine:
                raise ValueError("engine must match across archived paper reports")
            if report.engine_version != reference.engine_version:
                raise ValueError("engine_version must match across archived paper reports")
            if report.venue != reference.venue:
                raise ValueError("venue must match across archived paper reports")

    def _write(self, reports: list[PaperForwardReport]) -> None:
        self._validate_collection(reports)
        envelope = {
            "version": self.VERSION,
            "reports": self._canonical_reports(reports),
            "archive_hash": self._hash_reports(reports),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(envelope, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self._path)

    def load(self) -> tuple[PaperForwardReport, ...]:
        if not self._path.exists():
            return ()
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("paper report archive integrity check failed") from exc
        if not isinstance(envelope, dict):
            raise ValueError("paper report archive integrity check failed")
        if envelope.get("version") != self.VERSION:
            raise ValueError("unsupported paper report archive version")
        raw_reports = envelope.get("reports")
        archive_hash = envelope.get("archive_hash")
        if not isinstance(raw_reports, list) or not isinstance(archive_hash, str):
            raise ValueError("paper report archive integrity check failed")
        if self._hash_raw_reports(raw_reports) != archive_hash:
            raise ValueError("paper report archive integrity check failed")
        try:
            reports = [
                PaperForwardReport(**raw)
                for raw in raw_reports
                if isinstance(raw, dict)
            ]
        except (TypeError, ValueError) as exc:
            raise ValueError("paper report archive integrity check failed") from exc
        if len(reports) != len(raw_reports):
            raise ValueError("paper report archive integrity check failed")
        self._validate_collection(reports)
        return tuple(reports)

    def append(self, report: PaperForwardReport) -> None:
        reports = list(self.load())
        for existing in reports:
            if existing.session_id != report.session_id:
                continue
            if existing == report:
                # A service restart may replay report finalization after the
                # session state was persisted. Identical provenance is a no-op.
                return
            raise ValueError("conflicting paper report already exists for session_id")
        reports.append(report)
        self._write(reports)
