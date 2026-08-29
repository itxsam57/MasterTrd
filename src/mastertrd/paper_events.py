from __future__ import annotations

from .paper_session import PaperSessionJournal


class NautilusPaperEventSink:
    """Fail-closed adapter from Nautilus execution events to the paper journal."""

    def __init__(self, journal: PaperSessionJournal):
        self._journal = journal
        self._closed_positions = 0

    @property
    def closed_positions(self) -> int:
        return self._closed_positions

    def on_position_closed(self, event) -> None:
        from nautilus_trader.model.events import PositionClosed

        if not isinstance(event, PositionClosed):
            raise TypeError("paper journal accepts only Nautilus PositionClosed events")

        event_id = str(event.event_id)
        timestamp_ns = int(event.ts_event)
        realized_return = float(event.realized_return)
        self._journal.record_closed_trade(
            event_id,
            realized_return,
            timestamp_ns=timestamp_ns,
        )
        self._closed_positions += 1
