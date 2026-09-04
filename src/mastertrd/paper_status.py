from __future__ import annotations

import argparse
import json
import time

from mastertrd.paper_session import JsonPaperSessionStore, PaperSessionJournal


_STRATEGY_TELEMETRY_FIELDS = (
    "bars_seen",
    "bars_required",
    "warmup_remaining",
    "bootstrap_bars",
    "live_bars",
    "last_signal",
    "last_signal_reason",
    "last_exit_reason",
    "orders_attempted",
    "orders_allowed",
    "orders_rejected",
    "last_risk_rejection",
    "expected_closed_bars",
    "ws_closed_bars",
    "rest_recovered_bars",
    "missing_closed_bars",
    "recovery_failures",
    "last_closed_bar_ms",
    "last_expected_close_ms",
    "last_recovery_error",
    "data_healthy",
)


def paper_status_payload(
    journal: PaperSessionJournal,
    *,
    observed_ns: int,
) -> dict[str, object]:
    observed_ns = int(observed_ns)
    if observed_ns < journal.started_ns:
        raise ValueError("observed_ns cannot be before session start")
    if observed_ns < journal.latest_timestamp_ns:
        raise ValueError("observed_ns cannot be before the latest session event")

    trade_returns = [float(event.value) for event in journal._events if event.kind == "closed_trade"]
    reconciliation = [bool(event.value) for event in journal._events if event.kind == "reconciliation"]
    market_events = sum(1 for event in journal._events if event.kind == "market_event")

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in trade_returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0.0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    execution_state = journal.execution_state_checkpoint
    payload: dict[str, object] = {
        "schema_version": 1,
        "strategy_id": journal.strategy_id,
        "genome_hash": journal.genome_hash,
        "code_hash": journal.code_hash,
        "session_id": journal.session_id,
        "duration_seconds": (observed_ns - journal.started_ns) // 1_000_000_000,
        "market_events": market_events,
        "closed_trades": len(trade_returns),
        "total_return": equity - 1.0,
        "max_drawdown": max_drawdown,
        "reconciliation_checks": len(reconciliation),
        "reconciliation_errors": sum(1 for ok in reconciliation if not ok),
        "position_count": 0 if execution_state is None else len(execution_state.positions),
        "open_order_count": 0 if execution_state is None else len(execution_state.open_order_ids),
        "latest_timestamp_ns": journal.latest_timestamp_ns,
        "finalized": journal.finalized_report is not None,
    }
    # PAPER Status can be newer than the currently deployed read-only journal
    # reader during a rolling upgrade. Pre-telemetry journals legitimately lack
    # this attribute; all canonical identity/evidence above must still be
    # reportable without weakening validation or fabricating telemetry.
    telemetry = getattr(journal, "strategy_telemetry", None)
    if telemetry is not None:
        for key in _STRATEGY_TELEMETRY_FIELDS:
            if key in telemetry:
                payload[key] = telemetry[key]
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Emit a sanitized read-only PAPER runtime status snapshot")
    parser.add_argument("--session-state", required=True)
    args = parser.parse_args()
    journal = JsonPaperSessionStore(args.session_state).load()
    print(json.dumps(paper_status_payload(journal, observed_ns=time.time_ns()), sort_keys=True))
