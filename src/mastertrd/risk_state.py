from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import time
from typing import Callable

from .risk import RiskSnapshot
from .risk_runtime import OrderIntent


def _finite(value: float, *, field: str) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{field} must be finite")
    return numeric


def _non_negative(value: float, *, field: str) -> float:
    numeric = _finite(value, field=field)
    if numeric < 0.0:
        raise ValueError(f"{field} must be non-negative")
    return numeric


@dataclass(frozen=True, slots=True)
class AccountRiskState:
    symbol_exposure: float
    portfolio_exposure: float
    daily_pnl: float
    drawdown: float
    leverage: float
    correlated_exposure: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_exposure", _non_negative(self.symbol_exposure, field="symbol_exposure"))
        object.__setattr__(self, "portfolio_exposure", _non_negative(self.portfolio_exposure, field="portfolio_exposure"))
        object.__setattr__(self, "daily_pnl", _finite(self.daily_pnl, field="daily_pnl"))
        object.__setattr__(self, "drawdown", _non_negative(self.drawdown, field="drawdown"))
        object.__setattr__(self, "leverage", _non_negative(self.leverage, field="leverage"))
        object.__setattr__(self, "correlated_exposure", _non_negative(self.correlated_exposure, field="correlated_exposure"))


@dataclass(frozen=True, slots=True)
class MarketRiskState:
    spread_bps: float
    realized_volatility: float
    observed_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "spread_bps", _non_negative(self.spread_bps, field="spread_bps"))
        object.__setattr__(self, "realized_volatility", _non_negative(self.realized_volatility, field="realized_volatility"))
        object.__setattr__(self, "observed_at", _finite(self.observed_at, field="observed_at"))


@dataclass(frozen=True, slots=True)
class ReconciliationRiskState:
    ok: bool
    observed_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", _finite(self.observed_at, field="observed_at"))


@dataclass(frozen=True, slots=True)
class VenueRiskState:
    healthy: bool
    api_error_rate: float
    api_latency_ms: float

    def __post_init__(self) -> None:
        error_rate = _non_negative(self.api_error_rate, field="api_error_rate")
        if error_rate > 1.0:
            raise ValueError("api_error_rate must be between zero and one")
        object.__setattr__(self, "api_error_rate", error_rate)
        object.__setattr__(self, "api_latency_ms", _non_negative(self.api_latency_ms, field="api_latency_ms"))


class RiskStateProvider:
    """Own mutable execution-risk state and produce fail-closed order snapshots.

    This provider is intended for PAPER/DEMO/TESTNET/LIVE execution paths. It
    never interprets absent execution state as healthy. Historical simulation
    must opt into :class:`SimulationRiskStateProvider` explicitly.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        max_market_age_seconds: float = 5.0,
    ) -> None:
        self._clock = clock
        self.max_market_age_seconds = _non_negative(
            max_market_age_seconds,
            field="max_market_age_seconds",
        )
        self._accounts: dict[tuple[str, str], AccountRiskState] = {}
        self._markets: dict[str, MarketRiskState] = {}
        self._reconciliation: ReconciliationRiskState | None = None
        self._venues: dict[str, VenueRiskState] = {}

    def update_account_state(
        self,
        *,
        symbol: str,
        portfolio_id: str,
        symbol_exposure: float,
        portfolio_exposure: float,
        daily_pnl: float,
        drawdown: float,
        leverage: float,
        correlated_exposure: float,
    ) -> None:
        if not symbol or not portfolio_id:
            raise ValueError("symbol and portfolio_id are required")
        self._accounts[(portfolio_id, symbol)] = AccountRiskState(
            symbol_exposure=symbol_exposure,
            portfolio_exposure=portfolio_exposure,
            daily_pnl=daily_pnl,
            drawdown=drawdown,
            leverage=leverage,
            correlated_exposure=correlated_exposure,
        )

    def update_market_state(
        self,
        *,
        symbol: str,
        spread_bps: float,
        realized_volatility: float,
        observed_at: float,
    ) -> None:
        if not symbol:
            raise ValueError("symbol is required")
        self._markets[symbol] = MarketRiskState(
            spread_bps=spread_bps,
            realized_volatility=realized_volatility,
            observed_at=observed_at,
        )

    def update_reconciliation(self, *, ok: bool, observed_at: float) -> None:
        self._reconciliation = ReconciliationRiskState(ok=bool(ok), observed_at=observed_at)

    def update_venue_state(
        self,
        *,
        venue: str,
        healthy: bool,
        api_error_rate: float,
        api_latency_ms: float,
    ) -> None:
        if not venue:
            raise ValueError("venue is required")
        self._venues[venue] = VenueRiskState(
            healthy=bool(healthy),
            api_error_rate=api_error_rate,
            api_latency_ms=api_latency_ms,
        )

    @staticmethod
    def _order_notional(intent: OrderIntent, reference_price: float) -> tuple[float, bool]:
        price = float(reference_price)
        valid = isfinite(price) and price > 0.0
        return (abs(float(intent.quantity) * price) if valid else 0.0, valid)

    def snapshot(self, intent: OrderIntent, reference_price: float) -> RiskSnapshot:
        now = _finite(self._clock(), field="clock")
        account = self._accounts.get((intent.portfolio_id, intent.symbol))
        market = self._markets.get(intent.symbol)
        reconciliation = self._reconciliation
        venue = self._venues.get(intent.venue)
        order_notional, reference_price_ok = self._order_notional(intent, reference_price)

        market_age = float("inf") if market is None else max(0.0, now - market.observed_at)
        reconciliation_age = (
            float("inf")
            if reconciliation is None
            else max(0.0, now - reconciliation.observed_at)
        )

        return RiskSnapshot(
            order_notional=order_notional,
            symbol_exposure=0.0 if account is None else account.symbol_exposure,
            portfolio_exposure=0.0 if account is None else account.portfolio_exposure,
            daily_pnl=0.0 if account is None else account.daily_pnl,
            drawdown=0.0 if account is None else account.drawdown,
            orders_last_minute=0,
            data_stale=market is None or market_age > self.max_market_age_seconds,
            reconciliation_ok=False if reconciliation is None else reconciliation.ok,
            emergency_stop=account is None or not reference_price_ok,
            leverage=0.0 if account is None else account.leverage,
            correlated_exposure=0.0 if account is None else account.correlated_exposure,
            spread_bps=0.0 if market is None else market.spread_bps,
            realized_volatility=0.0 if market is None else market.realized_volatility,
            venue_healthy=False if venue is None else venue.healthy,
            api_error_rate=1.0 if venue is None else venue.api_error_rate,
            api_latency_ms=float("inf") if venue is None else venue.api_latency_ms,
            reconciliation_age_seconds=reconciliation_age,
        )


class SimulationRiskStateProvider:
    """Explicit permissive state provider for historical simulation only."""

    def snapshot(self, intent: OrderIntent, reference_price: float) -> RiskSnapshot:
        order_notional, valid = RiskStateProvider._order_notional(intent, reference_price)
        return RiskSnapshot(
            order_notional=order_notional,
            symbol_exposure=0.0,
            portfolio_exposure=0.0,
            daily_pnl=0.0,
            drawdown=0.0,
            orders_last_minute=0,
            data_stale=False,
            reconciliation_ok=True,
            emergency_stop=not valid,
            leverage=0.0,
            correlated_exposure=0.0,
            spread_bps=0.0,
            realized_volatility=0.0,
            venue_healthy=True,
            api_error_rate=0.0,
            api_latency_ms=0.0,
            reconciliation_age_seconds=0.0,
        )
