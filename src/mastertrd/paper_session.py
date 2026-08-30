from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
from typing import Literal

from .paper_evidence import PaperStartReceipt
from .paper_forward import PaperForwardReport


@dataclass(frozen=True, slots=True)
class _PaperSessionEvent:
    kind: Literal["closed_trade", "reconciliation", "market_event"]
    event_id: str
    timestamp_ns: int
    value: float | bool


class PaperSessionJournal:
    def __init__(self, receipt: PaperStartReceipt, *, code_hash: str, started_ns: int):
        if not receipt.connected:
            raise ValueError("paper session receipt must be connected")
        if receipt.engine != "nautilus_trader" or receipt.venue != "SANDBOX":
            raise ValueError("paper session must use Nautilus SANDBOX")
        if not code_hash:
            raise ValueError("code_hash is required")
        if started_ns < 0:
            raise ValueError("started_ns cannot be negative")

        self._receipt = receipt
        self._code_hash = code_hash
        self._started_ns = int(started_ns)
        self._events: list[_PaperSessionEvent] = []
        self._event_ids: set[str] = set()
        self._finalized = False

    @property
    def session_id(self) -> str:
        return self._receipt.session_id

    @property
    def latest_timestamp_ns(self) -> int:
        if self._events:
            return self._events[-1].timestamp_ns
        return self._started_ns

    def has_event(self, event_id: str) -> bool:
        return event_id in self._event_ids

    def _append(self, event: _PaperSessionEvent) -> None:
        if self._finalized:
            raise ValueError("paper session is already finalized")
        if not event.event_id:
            raise ValueError("event_id is required")
        if event.event_id in self._event_ids:
            raise ValueError("paper session event_id values must be unique")
        if event.timestamp_ns < self._started_ns:
            raise ValueError("paper session event cannot occur before session start")
        if self._events and event.timestamp_ns < self._events[-1].timestamp_ns:
            raise ValueError("paper session events must be append-only in timestamp order")
        self._events.append(event)
        self._event_ids.add(event.event_id)

    def record_market_event(self, event_id: str, *, timestamp_ns: int) -> None:
        self._append(_PaperSessionEvent("market_event", event_id, int(timestamp_ns), True))

    def record_closed_trade(self, trade_id: str, realized_return: float, *, timestamp_ns: int) -> None:
        value = float(realized_return)
        if not isfinite(value) or value < -1.0:
            raise ValueError("realized_return must be finite and cannot be below -1")
        self._append(_PaperSessionEvent("closed_trade", trade_id, int(timestamp_ns), value))

    def record_reconciliation(self, check_id: str, *, ok: bool, timestamp_ns: int) -> None:
        self._append(_PaperSessionEvent("reconciliation", check_id, int(timestamp_ns), bool(ok)))

    def _persistence_payload(self) -> dict[str, object]:
        return {
            "receipt": asdict(self._receipt),
            "code_hash": self._code_hash,
            "started_ns": self._started_ns,
            "events": [asdict(event) for event in self._events],
            "finalized": self._finalized,
        }

    @classmethod
    def _restore(cls, payload: dict[str, object]) -> "PaperSessionJournal":
        try:
            receipt_raw = payload["receipt"]
            if not isinstance(receipt_raw, dict):
                raise TypeError("receipt must be an object")
            receipt = PaperStartReceipt(**receipt_raw)
            code_hash = str(payload["code_hash"])
            started_ns = int(payload["started_ns"])
            events = payload["events"]
            finalized = bool(payload.get("finalized", False))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("paper session state is invalid") from exc
        if not isinstance(events, list):
            raise ValueError("paper session state is invalid")

        journal = cls(receipt, code_hash=code_hash, started_ns=started_ns)
        for raw in events:
            if not isinstance(raw, dict):
                raise ValueError("paper session state is invalid")
            try:
                kind = raw["kind"]
                event_id = str(raw["event_id"])
                timestamp_ns = int(raw["timestamp_ns"])
                value = raw["value"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("paper session state is invalid") from exc
            if kind == "market_event":
                if value is not True:
                    raise ValueError("paper session state is invalid")
                journal.record_market_event(event_id, timestamp_ns=timestamp_ns)
            elif kind == "closed_trade":
                journal.record_closed_trade(event_id, float(value), timestamp_ns=timestamp_ns)
            elif kind == "reconciliation":
                if not isinstance(value, bool):
                    raise ValueError("paper session state is invalid")
                journal.record_reconciliation(event_id, ok=value, timestamp_ns=timestamp_ns)
            else:
                raise ValueError("paper session state is invalid")
        journal._finalized = finalized
        return journal

    def finalize(self, *, ended_ns: int) -> PaperForwardReport:
        if self._finalized:
            raise ValueError("paper session is already finalized")
        ended_ns = int(ended_ns)
        if ended_ns < self._started_ns:
            raise ValueError("ended_ns cannot be before session start")
        if self._events and ended_ns < self._events[-1].timestamp_ns:
            raise ValueError("ended_ns cannot be before the latest session event")

        trade_returns = [float(event.value) for event in self._events if event.kind == "closed_trade"]
        reconciliation = [bool(event.value) for event in self._events if event.kind == "reconciliation"]

        equity = 1.0
        peak = 1.0
        max_drawdown = 0.0
        for value in trade_returns:
            equity *= 1.0 + value
            peak = max(peak, equity)
            if peak > 0.0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)

        payload = {
            "receipt_hash": self._receipt.receipt_hash,
            "code_hash": self._code_hash,
            "started_ns": self._started_ns,
            "ended_ns": ended_ns,
            "events": [
                {
                    "kind": event.kind,
                    "event_id": event.event_id,
                    "timestamp_ns": event.timestamp_ns,
                    "value": event.value,
                }
                for event in self._events
            ],
        }
        session_event_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        self._finalized = True
        return PaperForwardReport(
            strategy_id=self._receipt.strategy_id,
            genome_hash=self._receipt.genome_hash,
            session_id=self._receipt.session_id,
            venue=self._receipt.venue,
            engine=self._receipt.engine,
            engine_version=self._receipt.engine_version,
            duration_seconds=(ended_ns - self._started_ns) // 1_000_000_000,
            closed_trades=len(trade_returns),
            total_return=equity - 1.0,
            max_drawdown=max_drawdown,
            reconciliation_errors=sum(1 for ok in reconciliation if not ok),
            completed=bool(reconciliation),
            code_hash=self._code_hash,
            reconciliation_checks=len(reconciliation),
            session_event_hash=session_event_hash,
            provenance_verified=True,
        )


class JsonPaperSessionStore:
    VERSION = 1

    def __init__(self, path: str | Path):
        self._path = Path(path)

    @staticmethod
    def _hash_payload(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def save(self, journal: PaperSessionJournal) -> None:
        payload = journal._persistence_payload()
        envelope = {
            "version": self.VERSION,
            "payload": payload,
            "state_hash": self._hash_payload(payload),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(envelope, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, self._path)

    def load(self) -> PaperSessionJournal:
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("paper session state integrity check failed") from exc
        if not isinstance(envelope, dict):
            raise ValueError("paper session state integrity check failed")
        payload = envelope.get("payload")
        state_hash = envelope.get("state_hash")
        if not isinstance(payload, dict) or not isinstance(state_hash, str):
            raise ValueError("paper session state integrity check failed")
        if self._hash_payload(payload) != state_hash:
            raise ValueError("paper session state integrity check failed")
        if envelope.get("version") != self.VERSION:
            raise ValueError("unsupported paper session state version")
        return PaperSessionJournal._restore(payload)
