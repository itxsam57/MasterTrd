from __future__ import annotations

import hashlib

from .paper_session import PaperSessionJournal


class NautilusPaperEventSink:
    """Fail-closed adapter from Nautilus execution events to the paper journal."""

    def __init__(self, journal: PaperSessionJournal):
        self._journal = journal
        self._closed_positions = 0

    @property
    def closed_positions(self) -> int:
        return self._closed_positions

    def bind_journal(self, journal: PaperSessionJournal) -> None:
        """Move evidence recording to a fresh window without replacing Nautilus."""
        if not isinstance(journal, PaperSessionJournal):
            raise TypeError("journal must be a PaperSessionJournal")
        current = self._journal
        if journal.strategy_id != current.strategy_id:
            raise ValueError("paper event journal strategy identity changed")
        if journal.genome_hash != current.genome_hash:
            raise ValueError("paper event journal genome identity changed")
        if journal.code_hash != current.code_hash:
            raise ValueError("paper event journal code identity changed")
        if journal.session_id == current.session_id:
            raise ValueError("paper event journal rotation requires a new session identity")
        if journal.finalized_report is not None:
            raise ValueError("paper event journal cannot bind to a finalized session")
        self._journal = journal

    def on_position_closed(self, event) -> None:
        from nautilus_trader.model.events import PositionClosed

        if not isinstance(event, PositionClosed):
            raise TypeError("paper journal accepts only Nautilus PositionClosed events")

        # Stable NautilusTrader 1.231 includes event_id in PositionClosed repr but
        # does not expose it as a Python attribute. Build an idempotent fingerprint
        # from stable close-cycle identity fields exposed by that pinned API.
        ts_closed = int(event.ts_closed)
        if ts_closed <= 0:
            raise ValueError("PositionClosed must have a positive ts_closed")
        identity = (
            f"{event.position_id}|{event.closing_order_id}|{ts_closed}|"
            f"{float(event.realized_return):.17g}"
        )
        event_id = "position-close-" + hashlib.sha256(identity.encode()).hexdigest()
        self._journal.record_closed_trade(
            event_id,
            float(event.realized_return),
            timestamp_ns=ts_closed,
        )
        self._closed_positions += 1