from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile


ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PaperFill:
    event_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = ZERO


@dataclass(slots=True)
class PaperPosition:
    quantity: Decimal = ZERO
    average_price: Decimal = ZERO


@dataclass(slots=True)
class PaperLedger:
    initial_cash: Decimal
    cash: Decimal
    realized_pnl: Decimal = ZERO
    fees_paid: Decimal = ZERO
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    processed_event_ids: set[str] = field(default_factory=set)

    @classmethod
    def create(cls, *, initial_cash: Decimal) -> "PaperLedger":
        if initial_cash < ZERO:
            raise ValueError("initial_cash must be non-negative")
        return cls(initial_cash=initial_cash, cash=initial_cash)

    def apply(self, fill: PaperFill) -> bool:
        if fill.event_id in self.processed_event_ids:
            return False
        if not fill.event_id or not fill.symbol:
            raise ValueError("event_id and symbol are required")
        if fill.quantity <= ZERO or fill.price <= ZERO:
            raise ValueError("quantity and price must be positive")
        if fill.fee < ZERO:
            raise ValueError("fee must be non-negative")

        side = fill.side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        delta = fill.quantity if side == "BUY" else -fill.quantity
        position = self.positions.setdefault(fill.symbol, PaperPosition())
        old_qty = position.quantity
        old_avg = position.average_price
        new_qty = old_qty + delta

        if old_qty == ZERO or old_qty * delta > ZERO:
            old_notional = abs(old_qty) * old_avg
            added_notional = abs(delta) * fill.price
            position.average_price = (old_notional + added_notional) / abs(new_qty)
        else:
            closed_qty = min(abs(old_qty), abs(delta))
            direction = Decimal("1") if old_qty > ZERO else Decimal("-1")
            self.realized_pnl += (fill.price - old_avg) * closed_qty * direction
            if new_qty == ZERO:
                position.average_price = ZERO
            elif old_qty * new_qty < ZERO:
                position.average_price = fill.price
            else:
                position.average_price = old_avg

        position.quantity = new_qty
        self.cash -= delta * fill.price
        self.cash -= fill.fee
        self.fees_paid += fill.fee
        self.processed_event_ids.add(fill.event_id)
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_cash": str(self.initial_cash),
            "cash": str(self.cash),
            "realized_pnl": str(self.realized_pnl),
            "fees_paid": str(self.fees_paid),
            "positions": {
                symbol: {
                    "quantity": str(position.quantity),
                    "average_price": str(position.average_price),
                }
                for symbol, position in sorted(self.positions.items())
            },
            "processed_event_ids": sorted(self.processed_event_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "PaperLedger":
        positions_payload = payload.get("positions", {})
        if not isinstance(positions_payload, dict):
            raise ValueError("positions must be an object")
        positions: dict[str, PaperPosition] = {}
        for symbol, raw in positions_payload.items():
            if not isinstance(symbol, str) or not isinstance(raw, dict):
                raise ValueError("invalid position state")
            positions[symbol] = PaperPosition(
                quantity=Decimal(str(raw["quantity"])),
                average_price=Decimal(str(raw["average_price"])),
            )
        raw_events = payload.get("processed_event_ids", [])
        if not isinstance(raw_events, list) or not all(isinstance(item, str) for item in raw_events):
            raise ValueError("processed_event_ids must be a list of strings")
        return cls(
            initial_cash=Decimal(str(payload["initial_cash"])),
            cash=Decimal(str(payload["cash"])),
            realized_pnl=Decimal(str(payload.get("realized_pnl", "0"))),
            fees_paid=Decimal(str(payload.get("fees_paid", "0"))),
            positions=positions,
            processed_event_ids=set(raw_events),
        )


@dataclass(frozen=True, slots=True)
class JsonPaperStateStore:
    path: Path

    def __init__(self, path: str | Path):
        object.__setattr__(self, "path", Path(path))

    def save(self, ledger: PaperLedger) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(ledger.to_dict(), sort_keys=True, separators=(",", ":"))
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    def load(self) -> PaperLedger:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("paper state must be a JSON object")
        return PaperLedger.from_dict(payload)
