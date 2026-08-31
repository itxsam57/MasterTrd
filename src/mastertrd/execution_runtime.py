from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .reconciliation import ExecutionState, Reconciler, ReconciliationResult
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
        self._startup_reconciled = False

    @staticmethod
    def _risk_symbol(event: MarketStreamEvent) -> str:
        instrument = event.data.instrument
        if "." in instrument:
            return instrument
        return f"{instrument}.{event.data.venue}"

    def _refresh_market_risk_state(self, event: MarketStreamEvent) -> None:
        extras = event.data.extras
        volatility_raw = extras.get("realized_volatility")
        if volatility_raw is None:
            return
        try:
            realized_volatility = float(volatility_raw)
        except (TypeError, ValueError):
            return
        if not isfinite(realized_volatility) or realized_volatility < 0.0:
            return

        if event.kind == "tick":
            tick = event.tick
            midpoint = (float(tick.bid) + float(tick.ask)) / 2.0
            if midpoint <= 0.0:
                return
            spread_bps = ((float(tick.ask) - float(tick.bid)) / midpoint) * 10_000.0
        else:
            spread_raw = extras.get("spread_bps")
            if spread_raw is None:
                return
            try:
                spread_bps = float(spread_raw)
            except (TypeError, ValueError):
                return
            if not isfinite(spread_bps) or spread_bps < 0.0:
                return

        self._risk_runtime.update_market_state(
            symbol=self._risk_symbol(event),
            spread_bps=spread_bps,
            realized_volatility=realized_volatility,
            observed_at=event.timestamp_ns / 1_000_000_000.0,
        )

    def _reconcile(self) -> ReconciliationResult:
        return self._reconciler.reconcile(
            self._engine_state(),
            self._venue_state(),
        )

    def _record_reconciliation(
        self,
        *,
        reconciliation: ReconciliationResult,
        reconciliation_id: str,
        timestamp_ns: int,
    ) -> None:
        self._risk_runtime.update_reconciliation_state(
            ok=reconciliation.ok,
            observed_at=timestamp_ns / 1_000_000_000.0,
        )
        self._journal.record_reconciliation(
            reconciliation_id,
            ok=reconciliation.ok,
            timestamp_ns=timestamp_ns,
        )
        self._session_store.save(self._journal)

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

            if not self._startup_reconciled:
                startup_reconciliation = self._reconcile()
                reconciliation_checks += 1
                if not startup_reconciliation.ok:
                    reconciliation_errors += 1
                startup_timestamp = max(event.timestamp_ns, self._journal.latest_timestamp_ns)
                self._record_reconciliation(
                    reconciliation=startup_reconciliation,
                    reconciliation_id=f"reconcile:startup:{event.event_id}",
                    timestamp_ns=startup_timestamp,
                )
                if not startup_reconciliation.ok:
                    self._risk_runtime.kill(KillScope.SYSTEM, startup_reconciliation.summary)
                    system_killed = True
                    break
                self._startup_reconciled = True

            # Persist identity before dispatch. A crash may suppress this event on
            # restart, but it can never cause the same market event to submit twice.
            self._journal.record_market_event(event.event_id, timestamp_ns=event.timestamp_ns)
            self._session_store.save(self._journal)

            # Fresh market state must exist before a strategy can submit against
            # this event. Missing or malformed required metrics remain absent and
            # therefore fail closed in RiskStateProvider.
            self._refresh_market_risk_state(event)
            self._dispatch(event)
            processed_events += 1

            reconciliation = self._reconcile()
            reconciliation_checks += 1
            if not reconciliation.ok:
                reconciliation_errors += 1

            reconciliation_timestamp = max(event.timestamp_ns, self._journal.latest_timestamp_ns)
            self._record_reconciliation(
                reconciliation=reconciliation,
                reconciliation_id=f"reconcile:{event.event_id}",
                timestamp_ns=reconciliation_timestamp,
            )

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
