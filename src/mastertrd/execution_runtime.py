from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .reconciliation import ExecutionState, Reconciler
from .risk_runtime import KillScope, RiskRuntime
from .streaming import MarketStream, MarketStreamEvent


@dataclass(frozen=True, slots=True)
class RuntimeRunReport:
    processed_events: int
    duplicate_events: int
    reconciliation_checks: int
    reconciliation_errors: int
    system_killed: bool


class ExecutionRuntime:
    def __init__(
        self,
        *,
        journal: PaperSessionJournal,
        session_store: JsonPaperSessionStore,
        risk_runtime: RiskRuntime,
        reconciler: Reconciler,
        engine_state: Callable[[], ExecutionState],
        venue_state: Callable[[], ExecutionState],
        dispatch: Callable[[MarketStreamEvent], object],
        stream: MarketStream | None = None,
    ) -> None:
        self._journal = journal
        self._session_store = session_store
        self._risk_runtime = risk_runtime
        self._reconciler = reconciler
        self._engine_state = engine_state
        self._venue_state = venue_state
        self._dispatch = dispatch
        self._stream = stream

    def run(
        self,
        stream: MarketStream | None = None,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> RuntimeRunReport:
        active_stream = stream if stream is not None else self._stream
        if active_stream is None:
            raise ValueError("execution runtime requires a market stream")
        should_stop = stop_requested or (lambda: False)

        processed_events = 0
        duplicate_events = 0
        reconciliation_checks = 0
        reconciliation_errors = 0
        system_killed = False

        for event in active_stream:
            if should_stop():
                break
            if self._journal.has_event(event.event_id):
                duplicate_events += 1
                continue

            # Persist identity before dispatch. A crash may suppress this event on
            # restart, but it can never cause the same market event to submit twice.
            self._journal.record_market_event(event.event_id, timestamp_ns=event.timestamp_ns)
            self._session_store.save(self._journal)

            self._dispatch(event)
            processed_events += 1

            reconciliation = self._reconciler.reconcile(
                self._engine_state(),
                self._venue_state(),
            )
            reconciliation_checks += 1
            if not reconciliation.ok:
                reconciliation_errors += 1

            reconciliation_id = f"reconcile:{event.event_id}"
            reconciliation_timestamp = max(event.timestamp_ns, self._journal.latest_timestamp_ns)
            self._journal.record_reconciliation(
                reconciliation_id,
                ok=reconciliation.ok,
                timestamp_ns=reconciliation_timestamp,
            )
            self._session_store.save(self._journal)

            if not reconciliation.ok:
                self._risk_runtime.kill(KillScope.SYSTEM, reconciliation.summary)
                system_killed = True
                break

        return RuntimeRunReport(
            processed_events=processed_events,
            duplicate_events=duplicate_events,
            reconciliation_checks=reconciliation_checks,
            reconciliation_errors=reconciliation_errors,
            system_killed=system_killed,
        )
