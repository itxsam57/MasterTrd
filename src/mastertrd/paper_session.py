from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
from typing import Literal, Mapping

from .paper_evidence import PaperStartReceipt
from .paper_forward import PaperForwardReport
from .reconciliation import ExecutionState


@dataclass(frozen=True, slots=True)
class _PaperSessionEvent:
    kind: Literal["closed_trade", "reconciliation", "market_event", "strategy_telemetry"]
    event_id: str
    timestamp_ns: int
    value: float | bool | str


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
        self._execution_state: ExecutionState | None = None
        self._execution_state_timestamp_ns: int | None = None
        self._finalized = False
        self._final_report: PaperForwardReport | None = None

    @property
    def session_id(self) -> str:
        return self._receipt.session_id

    @property
    def strategy_id(self) -> str:
        return self._receipt.strategy_id

    @property
    def genome_hash(self) -> str:
        return self._receipt.genome_hash

    @property
    def code_hash(self) -> str:
        return self._code_hash

    @property
    def started_ns(self) -> int:
        return self._started_ns

    @property
    def latest_timestamp_ns(self) -> int:
        latest = self._events[-1].timestamp_ns if self._events else self._started_ns
        if self._execution_state_timestamp_ns is not None:
            latest = max(latest, self._execution_state_timestamp_ns)
        return latest

    @property
    def execution_state_checkpoint(self) -> ExecutionState | None:
        """Return the last integrity-covered execution state recorded for restart recovery."""
        return self._execution_state

    @property
    def finalized_report(self) -> PaperForwardReport | None:
        """Return the immutable persisted final report, if this session is closed."""
        return self._final_report

    @property
    def strategy_telemetry(self) -> dict[str, object] | None:
        for event in reversed(self._events):
            if event.kind != "strategy_telemetry":
                continue
            try:
                payload = json.loads(str(event.value))
            except json.JSONDecodeError as exc:
                raise RuntimeError("paper strategy telemetry is corrupt") from exc
            if not isinstance(payload, dict):
                raise RuntimeError("paper strategy telemetry is corrupt")
            return payload
        return None

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

    @staticmethod
    def _normalized_strategy_telemetry(telemetry: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(telemetry, Mapping):
            raise TypeError("strategy telemetry must be a mapping")
        required = {
            "bars_seen",
            "bars_required",
            "warmup_remaining",
            "last_signal",
            "last_signal_reason",
            "orders_attempted",
            "orders_rejected",
            "last_risk_rejection",
        }
        missing = required.difference(telemetry)
        if missing:
            raise ValueError(f"strategy telemetry is missing: {', '.join(sorted(missing))}")
        normalized = dict(telemetry)
        for key in ("bars_seen", "bars_required", "warmup_remaining", "orders_attempted", "orders_rejected"):
            value = normalized[key]
            if isinstance(value, bool):
                raise ValueError(f"strategy telemetry {key} must be an integer")
            try:
                integer = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"strategy telemetry {key} must be an integer") from exc
            if integer < 0 or (key == "bars_required" and integer <= 0):
                raise ValueError(f"strategy telemetry {key} is invalid")
            normalized[key] = integer
        if normalized["warmup_remaining"] > normalized["bars_required"]:
            raise ValueError("strategy telemetry warmup_remaining is invalid")
        if not isinstance(normalized["last_signal"], str) or not normalized["last_signal"]:
            raise ValueError("strategy telemetry last_signal is invalid")
        if not isinstance(normalized["last_signal_reason"], str) or not normalized["last_signal_reason"]:
            raise ValueError("strategy telemetry last_signal_reason is invalid")
        rejection = normalized["last_risk_rejection"]
        if rejection is not None and not isinstance(rejection, str):
            raise ValueError("strategy telemetry last_risk_rejection is invalid")
        if "data_healthy" in normalized and not isinstance(normalized["data_healthy"], bool):
            raise ValueError("strategy telemetry data_healthy must be a boolean")
        if "missing_closed_bars" in normalized:
            value = normalized["missing_closed_bars"]
            if isinstance(value, bool):
                raise ValueError("strategy telemetry missing_closed_bars must be an integer")
            try:
                integer = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("strategy telemetry missing_closed_bars must be an integer") from exc
            if integer < 0:
                raise ValueError("strategy telemetry missing_closed_bars is invalid")
            normalized["missing_closed_bars"] = integer
        # Ensure optional observability fields are safe JSON scalars/containers.
        try:
            json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("strategy telemetry must be JSON serializable") from exc
        return normalized

    def record_strategy_telemetry(
        self,
        telemetry: Mapping[str, object],
        *,
        timestamp_ns: int,
    ) -> None:
        normalized = self._normalized_strategy_telemetry(telemetry)
        value = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        event_id = f"strategy-telemetry:{len(self._events)}"
        self._append(_PaperSessionEvent("strategy_telemetry", event_id, int(timestamp_ns), value))

    def record_execution_state(self, state: ExecutionState, *, timestamp_ns: int) -> None:
        """Atomically checkpoint expected execution state for a future process restart."""
        if self._finalized:
            raise ValueError("paper session is already finalized")
        if not isinstance(state, ExecutionState):
            raise TypeError("state must be an ExecutionState")
        timestamp = int(timestamp_ns)
        if timestamp < self._started_ns:
            raise ValueError("execution state cannot occur before session start")
        if timestamp < self.latest_timestamp_ns:
            raise ValueError("execution state checkpoints must be monotonic")
        self._execution_state = state
        self._execution_state_timestamp_ns = timestamp

    def _execution_state_payload(self) -> dict[str, object] | None:
        if self._execution_state is None:
            return None
        if self._execution_state_timestamp_ns is None:
            raise RuntimeError("paper execution checkpoint timestamp is missing")
        return {
            "timestamp_ns": self._execution_state_timestamp_ns,
            "account_id": self._execution_state.account_id,
            "positions": {
                key: str(value) for key, value in sorted(self._execution_state.positions.items())
            },
            "open_order_ids": sorted(self._execution_state.open_order_ids),
            "balances": {
                key: str(value) for key, value in sorted(self._execution_state.balances.items())
            },
        }

    def _persistence_payload(self) -> dict[str, object]:
        return {
            "receipt": asdict(self._receipt),
            "code_hash": self._code_hash,
            "started_ns": self._started_ns,
            "events": [asdict(event) for event in self._events],
            "execution_state": self._execution_state_payload(),
            "finalized": self._finalized,
            "final_report": None if self._final_report is None else asdict(self._final_report),
        }

    @staticmethod
    def _validate_restored_report(
        report: PaperForwardReport,
        *,
        receipt: PaperStartReceipt,
        code_hash: str,
    ) -> None:
        expected = (
            (report.strategy_id, receipt.strategy_id, "strategy_id"),
            (report.genome_hash, receipt.genome_hash, "genome_hash"),
            (report.session_id, receipt.session_id, "session_id"),
            (report.venue, receipt.venue, "venue"),
            (report.engine, receipt.engine, "engine"),
            (report.engine_version, receipt.engine_version, "engine_version"),
            (report.code_hash, code_hash, "code_hash"),
        )
        for actual, required, field in expected:
            if actual != required:
                raise ValueError(f"paper session final report {field} mismatch")
        if not report.provenance_verified or not report.session_event_hash:
            raise ValueError("paper session final report provenance is invalid")

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
            execution_state_raw = payload.get("execution_state")
            finalized = bool(payload.get("finalized", False))
            final_report_raw = payload.get("final_report")
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
            elif kind == "strategy_telemetry":
                if not isinstance(value, str):
                    raise ValueError("paper session state is invalid")
                try:
                    telemetry = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError("paper session state is invalid") from exc
                if not isinstance(telemetry, dict):
                    raise ValueError("paper session state is invalid")
                expected_id = f"strategy-telemetry:{len(journal._events)}"
                if event_id != expected_id:
                    raise ValueError("paper session state is invalid")
                journal.record_strategy_telemetry(telemetry, timestamp_ns=timestamp_ns)
            else:
                raise ValueError("paper session state is invalid")

        if execution_state_raw is not None:
            if not isinstance(execution_state_raw, dict):
                raise ValueError("paper session execution state is invalid")
            try:
                checkpoint_timestamp = int(execution_state_raw["timestamp_ns"])
                account_id = str(execution_state_raw["account_id"])
                positions = execution_state_raw["positions"]
                open_order_ids = execution_state_raw["open_order_ids"]
                balances = execution_state_raw["balances"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("paper session execution state is invalid") from exc
            if (
                checkpoint_timestamp < started_ns
                or not isinstance(positions, dict)
                or not isinstance(open_order_ids, list)
                or not isinstance(balances, dict)
            ):
                raise ValueError("paper session execution state is invalid")
            try:
                restored_state = ExecutionState(
                    account_id=account_id,
                    positions=positions,
                    open_order_ids=frozenset(str(value) for value in open_order_ids),
                    balances=balances,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("paper session execution state is invalid") from exc
            journal._execution_state = restored_state
            journal._execution_state_timestamp_ns = checkpoint_timestamp

        if finalized:
            if not isinstance(final_report_raw, dict):
                raise ValueError("paper session finalized state is missing final report")
            try:
                final_report = PaperForwardReport(**final_report_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("paper session final report is invalid") from exc
            cls._validate_restored_report(final_report, receipt=receipt, code_hash=code_hash)
            journal._final_report = final_report
            journal._finalized = True
        elif final_report_raw is not None:
            raise ValueError("paper session non-finalized state cannot contain final report")
        return journal

    def finalize(self, *, ended_ns: int) -> PaperForwardReport:
        if self._finalized:
            raise ValueError("paper session is already finalized")
        ended_ns = int(ended_ns)
        if ended_ns < self._started_ns:
            raise ValueError("ended_ns cannot be before session start")
        if ended_ns < self.latest_timestamp_ns:
            raise ValueError("ended_ns cannot be before the latest session event")

        trade_returns = [float(event.value) for event in self._events if event.kind == "closed_trade"]
        reconciliation = [bool(event.value) for event in self._events if event.kind == "reconciliation"]
        telemetry = self.strategy_telemetry or {}
        data_healthy = telemetry.get("data_healthy", True)
        missing_closed_bars = telemetry.get("missing_closed_bars", 0)
        if not isinstance(data_healthy, bool):
            raise ValueError("paper strategy telemetry data_healthy is invalid")
        if isinstance(missing_closed_bars, bool) or not isinstance(missing_closed_bars, int):
            raise ValueError("paper strategy telemetry missing_closed_bars is invalid")
        if missing_closed_bars < 0:
            raise ValueError("paper strategy telemetry missing_closed_bars is invalid")

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
            "execution_state": self._execution_state_payload(),
        }
        session_event_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        report = PaperForwardReport(
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
            data_healthy=data_healthy,
            missing_closed_bars=missing_closed_bars,
        )
        self._final_report = report
        self._finalized = True
        return report


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
