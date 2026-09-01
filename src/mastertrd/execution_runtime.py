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
    session_rotations: int = 0


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
        finalizer: Callable[[], object] | None = None,
        startup_expected_state: Callable[[], ExecutionState] | None = None,
        rotation_requested: Callable[[], bool] | None = None,
        rotate_session: Callable[[int], tuple[PaperSessionJournal, JsonPaperSessionStore]] | None = None,
    ) -> None:
        if (rotation_requested is None) != (rotate_session is None):
            raise ValueError("rotation_requested and rotate_session must be configured together")
        self._journal = journal
        self._session_store = session_store
        self._risk_runtime = risk_runtime
        self._reconciler = reconciler
        self._engine_state = engine_state
        self._venue_state = venue_state
        self._dispatch = dispatch
        self._stream = stream
        self._finalizer = finalizer
        self._startup_expected_state = startup_expected_state
        self._rotation_requested = rotation_requested
        self._rotate_session = rotate_session
        self._closed = False
        self._startup_reconciled = False

    @staticmethod
    def _risk_symbol(event: MarketStreamEvent) -> str:
        instrument = event.data.instrument
        if "." in instrument:
            return instrument
        return f"{instrument}.{event.data.venue}"

    @staticmethod
    def _execution_state_is_flat(state: ExecutionState) -> bool:
        return not state.open_order_ids and all(quantity == 0 for quantity in state.positions.values())

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

    def _reconcile(self, *, startup: bool = False) -> ReconciliationResult:
        expected_state = (
            self._startup_expected_state
            if startup and self._startup_expected_state is not None
            else self._venue_state
        )
        return self._reconciler.reconcile(
            self._engine_state(),
            expected_state(),
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
        if reconciliation.ok:
            self._journal.record_execution_state(
                self._engine_state(),
                timestamp_ns=timestamp_ns,
            )
        self._session_store.save(self._journal)

    def _rotate_evidence_if_safe(self, *, ended_ns: int) -> bool:
        if self._rotation_requested is None or self._rotate_session is None:
            return False
        if not self._rotation_requested():
            return False
        if not self._execution_state_is_flat(self._engine_state()):
            return False

        previous = self._journal
        new_journal, new_store = self._rotate_session(int(ended_ns))
        if not isinstance(new_journal, PaperSessionJournal) or not isinstance(
            new_store, JsonPaperSessionStore
        ):
            raise TypeError("rotate_session must return a paper journal and session store")
        if new_journal.session_id == previous.session_id:
            raise RuntimeError("paper evidence rotation must create a new session identity")
        if new_journal.strategy_id != previous.strategy_id:
            raise RuntimeError("paper evidence rotation changed strategy identity")
        if new_journal.genome_hash != previous.genome_hash:
            raise RuntimeError("paper evidence rotation changed genome identity")
        if new_journal.code_hash != previous.code_hash:
            raise RuntimeError("paper evidence rotation changed code identity")
        if new_journal.finalized_report is not None:
            raise RuntimeError("paper evidence rotation returned a finalized session")

        self._journal = new_journal
        self._session_store = new_store
        # The execution engine remains in-process. The next market event still
        # receives a fresh reconciliation checkpoint for the new evidence window,
        # but no stale process-restart snapshot may leak across that boundary.
        self._startup_expected_state = None
        self._startup_reconciled = False
        return True

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
        session_rotations = 0

        for event in active_stream:
            if should_stop():
                break
            if self._journal.has_event(event.event_id):
                duplicate_events += 1
                continue

            if not self._startup_reconciled:
                startup_reconciliation = self._reconcile(startup=True)
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

            if self._rotate_evidence_if_safe(ended_ns=reconciliation_timestamp):
                session_rotations += 1

        return RuntimeRunReport(
            processed_events=processed_events,
            duplicate_events=duplicate_events,
            reconciliation_checks=reconciliation_checks,
            reconciliation_errors=reconciliation_errors,
            system_killed=system_killed,
            session_rotations=session_rotations,
        )

    def close(self) -> None:
        """Finalize owned execution resources exactly once."""
        if self._closed:
            return
        if self._finalizer is not None:
            self._finalizer()
        self._closed = True