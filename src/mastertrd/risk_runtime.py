from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from math import isfinite
import time
from typing import Callable, Protocol

from .risk import RiskAction, RiskLimits, RiskSnapshot, evaluate_risk


class KillScope(StrEnum):
    STRATEGY = "STRATEGY"
    SYMBOL = "SYMBOL"
    VENUE = "VENUE"
    PORTFOLIO = "PORTFOLIO"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    strategy_id: str
    symbol: str
    venue: str
    side: str
    quantity: float
    order_type: str
    portfolio_id: str = "default"

    def __post_init__(self) -> None:
        if not all(
            (
                self.strategy_id,
                self.symbol,
                self.venue,
                self.side,
                self.order_type,
                self.portfolio_id,
            )
        ):
            raise ValueError("order intent identity fields are required")
        if not isfinite(float(self.quantity)) or float(self.quantity) <= 0.0:
            raise ValueError("order intent quantity must be positive and finite")

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "order_type": self.order_type,
                "portfolio_id": self.portfolio_id,
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


class RiskStateSource(Protocol):
    def snapshot(self, intent: OrderIntent, reference_price: float) -> RiskSnapshot: ...


@dataclass(frozen=True, slots=True)
class RiskDecision:
    action: RiskAction
    reason: str
    intent: OrderIntent
    fingerprint: str
    checked_at: float


@dataclass(frozen=True, slots=True)
class VenueHealth:
    healthy: bool
    error_rate: float
    latency_ms: float

    def __post_init__(self) -> None:
        if not isfinite(float(self.error_rate)) or not 0.0 <= float(self.error_rate) <= 1.0:
            raise ValueError("error_rate must be finite and between 0 and 1")
        if not isfinite(float(self.latency_ms)) or float(self.latency_ms) < 0.0:
            raise ValueError("latency_ms must be finite and non-negative")


class RiskRuntime:
    def __init__(
        self,
        limits: RiskLimits,
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        state_provider: RiskStateSource | None = None,
    ) -> None:
        self.limits = limits
        self._clock = monotonic_clock
        self.state_provider = state_provider
        self.decisions: list[RiskDecision] = []
        self._last_allowed: dict[str, float] = {}
        self._allowed_order_times: deque[float] = deque()
        self._kills: dict[KillScope, dict[str, str]] = {
            KillScope.STRATEGY: {},
            KillScope.SYMBOL: {},
            KillScope.VENUE: {},
            KillScope.PORTFOLIO: {},
        }
        self._system_kill_reason: str | None = None
        self._venue_health: dict[str, VenueHealth] = {}
        self._portfolio_correlated_exposure: dict[str, float] = {}

    @property
    def allow_count(self) -> int:
        return sum(decision.action is RiskAction.ALLOW for decision in self.decisions)

    @property
    def accepted_decisions(self) -> tuple[RiskDecision, ...]:
        return tuple(decision for decision in self.decisions if decision.action is RiskAction.ALLOW)

    @property
    def accepted_order_fingerprints(self) -> tuple[str, ...]:
        return tuple(decision.fingerprint for decision in self.accepted_decisions)

    def snapshot_for_order(self, intent: OrderIntent, reference_price: float) -> RiskSnapshot:
        if self.state_provider is not None:
            return self.state_provider.snapshot(intent, reference_price)

        price = float(reference_price)
        valid_price = isfinite(price) and price > 0.0
        return RiskSnapshot(
            order_notional=abs(float(intent.quantity) * price) if valid_price else 0.0,
            symbol_exposure=0.0,
            portfolio_exposure=0.0,
            daily_pnl=0.0,
            drawdown=0.0,
            orders_last_minute=0,
            data_stale=True,
            reconciliation_ok=False,
            emergency_stop=True,
            leverage=0.0,
            correlated_exposure=0.0,
            spread_bps=0.0,
            realized_volatility=0.0,
            venue_healthy=False,
            api_error_rate=1.0,
            api_latency_ms=float("inf"),
            reconciliation_age_seconds=float("inf"),
        )

    def update_market_state(
        self,
        *,
        symbol: str,
        spread_bps: float,
        realized_volatility: float,
        observed_at: float,
    ) -> None:
        updater = getattr(self.state_provider, "update_market_state", None)
        if updater is not None:
            updater(
                symbol=symbol,
                spread_bps=spread_bps,
                realized_volatility=realized_volatility,
                observed_at=observed_at,
            )

    def update_reconciliation_state(self, *, ok: bool, observed_at: float) -> None:
        updater = getattr(self.state_provider, "update_reconciliation", None)
        if updater is not None:
            updater(ok=ok, observed_at=observed_at)

    def kill(self, scope: KillScope, reason: str, *, key: str | None = None) -> None:
        if not reason:
            raise ValueError("kill reason is required")
        if scope is KillScope.SYSTEM:
            self._system_kill_reason = reason
            return
        if scope not in self._kills:
            raise ValueError(f"unsupported kill scope: {scope}")
        if not key:
            raise ValueError(f"{scope.value.lower()} kill requires key")
        self._kills[scope][key] = reason

    def update_api_health(
        self,
        *,
        venue: str,
        healthy: bool,
        error_rate: float,
        latency_ms: float,
    ) -> None:
        if not venue:
            raise ValueError("venue is required")
        health = VenueHealth(
            healthy=bool(healthy),
            error_rate=float(error_rate),
            latency_ms=float(latency_ms),
        )
        self._venue_health[venue] = health
        updater = getattr(self.state_provider, "update_venue_state", None)
        if updater is not None:
            updater(
                venue=venue,
                healthy=health.healthy,
                api_error_rate=health.error_rate,
                api_latency_ms=health.latency_ms,
            )

    def update_correlated_exposure(self, *, portfolio_id: str, exposure: float) -> None:
        numeric = float(exposure)
        if not portfolio_id:
            raise ValueError("portfolio_id is required")
        if not isfinite(numeric) or numeric < 0.0:
            raise ValueError("correlated exposure must be finite and non-negative")
        self._portfolio_correlated_exposure[portfolio_id] = numeric

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

    def _manual_kill(self, intent: OrderIntent) -> tuple[RiskAction, str] | None:
        checks = (
            (KillScope.VENUE, intent.venue, RiskAction.KILL_VENUE),
            (KillScope.PORTFOLIO, intent.portfolio_id, RiskAction.KILL_PORTFOLIO),
            (KillScope.STRATEGY, intent.strategy_id, RiskAction.KILL_STRATEGY),
            (KillScope.SYMBOL, intent.symbol, RiskAction.KILL_SYMBOL),
        )
        for scope, key, action in checks:
            reason = self._kills[scope].get(key)
            if reason is not None:
                return action, reason
        return None

    def _accepted_orders_last_minute(self, checked_at: float) -> int:
        cutoff = checked_at - 60.0
        while self._allowed_order_times and self._allowed_order_times[0] <= cutoff:
            self._allowed_order_times.popleft()
        return len(self._allowed_order_times)

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

        manual = self._manual_kill(intent)
        if manual is not None:
            action, reason = manual
            return self._record(action, reason, intent, fingerprint, checked_at)

        previous = self._last_allowed.get(fingerprint)
        duplicate = snapshot.duplicate_order or (
            previous is not None
            and self.limits.duplicate_order_window_seconds > 0.0
            and checked_at - previous < self.limits.duplicate_order_window_seconds
        )
        health = self._venue_health.get(intent.venue)
        correlated = self._portfolio_correlated_exposure.get(
            intent.portfolio_id,
            float(snapshot.correlated_exposure),
        )
        owned_order_rate = self._accepted_orders_last_minute(checked_at)
        effective = replace(
            snapshot,
            duplicate_order=duplicate,
            orders_last_minute=max(int(snapshot.orders_last_minute), owned_order_rate),
            correlated_exposure=max(float(snapshot.correlated_exposure), correlated),
            venue_healthy=(snapshot.venue_healthy and health.healthy) if health else snapshot.venue_healthy,
            api_error_rate=max(float(snapshot.api_error_rate), health.error_rate) if health else snapshot.api_error_rate,
            api_latency_ms=max(float(snapshot.api_latency_ms), health.latency_ms) if health else snapshot.api_latency_ms,
        )
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
            self._allowed_order_times.append(checked_at)
        return decision
