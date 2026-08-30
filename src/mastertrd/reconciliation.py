from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping


Numeric = Decimal | int | float | str


def _decimal(value: Numeric, *, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _normalize_amounts(values: Mapping[str, Numeric], *, field: str) -> dict[str, Decimal]:
    normalized: dict[str, Decimal] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{field} keys must be non-empty strings")
        normalized[key] = _decimal(value, field=f"{field}:{key}")
    return normalized


@dataclass(frozen=True, slots=True)
class ExecutionState:
    account_id: str
    positions: Mapping[str, Numeric]
    open_order_ids: frozenset[str]
    balances: Mapping[str, Numeric]

    def __post_init__(self) -> None:
        if not self.account_id:
            raise ValueError("account_id is required")
        orders = frozenset(self.open_order_ids)
        if not all(isinstance(order_id, str) and order_id for order_id in orders):
            raise ValueError("open_order_ids must contain non-empty strings")
        object.__setattr__(self, "positions", _normalize_amounts(self.positions, field="position"))
        object.__setattr__(self, "open_order_ids", orders)
        object.__setattr__(self, "balances", _normalize_amounts(self.balances, field="balance"))


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    mismatches: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.mismatches

    @property
    def summary(self) -> str:
        if self.ok:
            return "reconciliation ok"
        return "reconciliation mismatch: " + ", ".join(self.mismatches)


class Reconciler:
    def __init__(self, *, tolerance: Numeric = Decimal("0")) -> None:
        self._tolerance = _decimal(tolerance, field="tolerance")
        if self._tolerance < 0:
            raise ValueError("tolerance cannot be negative")

    def _amount_mismatches(
        self,
        engine: Mapping[str, Decimal],
        venue: Mapping[str, Decimal],
        *,
        prefix: str,
    ) -> list[str]:
        mismatches: list[str] = []
        for key in sorted(set(engine) | set(venue)):
            if (key in engine) != (key in venue):
                mismatches.append(f"{prefix}:{key}")
                continue
            if abs(engine[key] - venue[key]) > self._tolerance:
                mismatches.append(f"{prefix}:{key}")
        return mismatches

    def reconcile(self, engine_state: ExecutionState, venue_state: ExecutionState) -> ReconciliationResult:
        mismatches: list[str] = []
        if engine_state.account_id != venue_state.account_id:
            mismatches.append("account_id")
        mismatches.extend(
            self._amount_mismatches(
                engine_state.positions,
                venue_state.positions,
                prefix="position",
            )
        )
        if engine_state.open_order_ids != venue_state.open_order_ids:
            mismatches.append("orders")
        mismatches.extend(
            self._amount_mismatches(
                engine_state.balances,
                venue_state.balances,
                prefix="balance",
            )
        )
        return ReconciliationResult(tuple(mismatches))
