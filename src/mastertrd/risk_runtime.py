from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from math import isfinite
import time
from typing import Callable

from .risk import RiskAction, RiskLimits, RiskSnapshot, evaluate_risk


class KillScope(StrEnum):
    STRATEGY = "STRATEGY"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    strategy_id: str
    symbol: str
    venue: str
    side: str
    quantity: float
    order_type: str

    def __post_init__(self) -> None:
        if not all((self.strategy_id, self.symbol, self.venue, self.side, self.order_type)):
            raise ValueError("order intent identity fields are required")
        if not isfinite(float(self.quantity)) or float(self.quantity) <= 0.0:
            raise ValueError("order intent quantity must be positive and finite")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "order_type": self.order_type,
                "quantity": float(self.quantity),
                "side": self.side,
                "strategy_id": self.strategy_id,
                "symbol": self.symbol,
                "venue": self.venue,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class RiskDecision:
    action: RiskAction
    reason: str
    intent: OrderIntent
    fingerprint: str
    checked_at: float


class RiskRuntime:
    def __init__(
        self,
        limits: RiskLimits,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits
        self._clock = monotonic_clock
        self.decisions: list[RiskDecision] = []
        self._last_allowed: dict[str, float] = {}
        self._strategy_kills: dict[str, str] = {}
        self._system_kill_reason: str | None = None

    @property
    def allow_count(self) -> int:
        return sum(decision.action is RiskAction.ALLOW for decision in self.decisions)

    @property
    def accepted_decisions(self) -> tuple[RiskDecision, ...]:
        return tuple(decision for decision in self.decisions if decision.action is RiskAction.ALLOW)

    @property
    def accepted_order_fingerprints(self) -> tuple[str, ...]:
        return tuple(decision.fingerprint for decision in self.accepted_decisions)

    def kill(self, scope: KillScope, reason: str, *, key: str | None = None) -> None:
        if not reason:
            raise ValueError("kill reason is required")
        if scope is KillScope.SYSTEM:
            self._system_kill_reason = reason
            return
        if scope is KillScope.STRATEGY:
            if not key:
                raise ValueError("strategy kill requires key")
            self._strategy_kills[key] = reason
            return
        raise ValueError(f"unsupported kill scope: {scope}")

    def _record(
        self,
        action: RiskAction,
        reason: str,
        intent: OrderIntent,
        fingerprint: str,
        checked_at: float,
    ) -> RiskDecision:
        decision = RiskDecision(action, reason, intent, fingerprint, checked_at)
        self.decisions.append(decision)
        return decision

    @staticmethod
    def _reason(action: RiskAction, snapshot: RiskSnapshot) -> str:
        if action is RiskAction.ALLOW:
            return "risk checks passed"
        if snapshot.duplicate_order:
            return "duplicate order inside configured window"
        if action is RiskAction.KILL_SYSTEM:
            return "system health or reconciliation risk limit breached"
        if action is RiskAction.KILL_STRATEGY:
            return "strategy loss or drawdown risk limit breached"
        return "order risk limit breached"

    def check_order(self, intent: OrderIntent, snapshot: RiskSnapshot) -> RiskDecision:
        checked_at = float(self._clock())
        fingerprint = intent.fingerprint

        if self._system_kill_reason is not None:
            return self._record(
                RiskAction.KILL_SYSTEM,
                self._system_kill_reason,
                intent,
                fingerprint,
                checked_at,
            )

        strategy_reason = self._strategy_kills.get(intent.strategy_id)
        if strategy_reason is not None:
            return self._record(
                RiskAction.KILL_STRATEGY,
                strategy_reason,
                intent,
                fingerprint,
                checked_at,
            )

        previous = self._last_allowed.get(fingerprint)
        duplicate = snapshot.duplicate_order or (
            previous is not None
            and self.limits.duplicate_order_window_seconds > 0.0
            and checked_at - previous < self.limits.duplicate_order_window_seconds
        )
        effective = replace(snapshot, duplicate_order=duplicate)
        action = evaluate_risk(self.limits, effective)
        decision = self._record(
            action,
            self._reason(action, effective),
            intent,
            fingerprint,
            checked_at,
        )
        if action is RiskAction.ALLOW:
            self._last_allowed[fingerprint] = checked_at
        return decision
