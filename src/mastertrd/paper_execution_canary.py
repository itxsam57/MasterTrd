from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from math import isclose, isfinite
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .binance_stream import BinancePublicMarketSource
from .execution_runtime import ExecutionRuntime
from .nautilus_paper import load_public_binance_spot_instrument
from .paper_evidence import PaperStartReceipt
from .paper_hardening import load_public_binance_bar_history
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .reconciliation import ExecutionState, Reconciler
from .risk_runtime import RiskRuntime
from .risk_state import RiskStateProvider
from .runtime_factory import _paper_risk_limits, _public_paper_first_expected_start_ms
from .streaming import MarketStream, MarketStreamEvent


@dataclass(frozen=True, slots=True)
class ExecutionCanaryLane:
    name: str
    source_timeframe: str
    target_minutes: int
    plan: tuple[str, ...]
    hold_source_bars: int
    minimum_real_closed_bars: int
    minimum_orders: int
    minimum_closed_positions: int
    test_only: bool = True
    counts_as_alpha: bool = False
    live_eligible: bool = False


def execution_canary_lanes() -> tuple[ExecutionCanaryLane, ...]:
    return (
        ExecutionCanaryLane("paper-1m-long", "1m", 1, ("LONG", "FLAT"), 0, 2, 2, 1),
        ExecutionCanaryLane("paper-3m-short", "3m", 3, ("SHORT", "FLAT"), 0, 2, 2, 1),
        ExecutionCanaryLane("paper-5m-reversal", "5m", 5, ("LONG", "SHORT", "FLAT"), 0, 3, 3, 2),
        ExecutionCanaryLane("paper-10m-hold-exit", "5m", 10, ("LONG", "HOLD", "FLAT"), 1, 3, 2, 1),
    )


def _integer(result: Mapping[str, object], key: str) -> int:
    value = result.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{key} must be an integer")
    return value


def _boolean(result: Mapping[str, object], key: str) -> bool:
    value = result.get(key)
    if not isinstance(value, bool):
        raise RuntimeError(f"{key} must be boolean")
    return value


def validate_execution_canary_result(lane: ExecutionCanaryLane, result: Mapping[str, object]) -> None:
    if result.get("lane") != lane.name:
        raise RuntimeError(f"{lane.name}: lane identity mismatch")
    if result.get("source_timeframe") != lane.source_timeframe:
        raise RuntimeError(f"{lane.name}: source_timeframe mismatch")
    if result.get("target_minutes") != lane.target_minutes:
        raise RuntimeError(f"{lane.name}: target_minutes mismatch")
    if tuple(result.get("plan", ())) != lane.plan:
        raise RuntimeError(f"{lane.name}: plan mismatch")
    if result.get("mode") != "PAPER":
        raise RuntimeError(f"{lane.name}: mode must be PAPER")
    if _boolean(result, "live_enabled"):
        raise RuntimeError(f"{lane.name}: live_enabled must be false")
    if not _boolean(result, "data_healthy"):
        raise RuntimeError(f"{lane.name}: data_healthy must be true")
    if _integer(result, "missing_closed_bars") != 0:
        raise RuntimeError(f"{lane.name}: missing_closed_bars must be zero")
    if _integer(result, "recovery_failures") != 0:
        raise RuntimeError(f"{lane.name}: recovery_failures must be zero")
    if _integer(result, "real_closed_bars") < lane.minimum_real_closed_bars:
        raise RuntimeError(f"{lane.name}: real_closed_bars below minimum")
    if _integer(result, "orders_attempted") < lane.minimum_orders:
        raise RuntimeError(f"{lane.name}: orders_attempted below minimum")
    if _integer(result, "orders_allowed") < lane.minimum_orders:
        raise RuntimeError(f"{lane.name}: orders_allowed below minimum")
    if _integer(result, "orders_rejected") != 0:
        raise RuntimeError(f"{lane.name}: orders_rejected must be zero")
    if _integer(result, "closed_positions") < lane.minimum_closed_positions:
        raise RuntimeError(f"{lane.name}: closed_positions below minimum")
    trade_returns_raw = result.get("closed_trade_returns")
    if not isinstance(trade_returns_raw, list):
        raise RuntimeError(f"{lane.name}: closed_trade_returns must be a list")
    try:
        trade_returns = [float(value) for value in trade_returns_raw]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{lane.name}: closed_trade_returns must be numeric") from exc
    if len(trade_returns) != _integer(result, "closed_positions"):
        raise RuntimeError(f"{lane.name}: closed_trade_returns count mismatch")
    if any(not isfinite(value) or value < -1.0 for value in trade_returns):
        raise RuntimeError(f"{lane.name}: closed_trade_returns contains invalid return")
    winning = sum(1 for value in trade_returns if value > 0.0)
    losing = sum(1 for value in trade_returns if value < 0.0)
    breakeven = sum(1 for value in trade_returns if value == 0.0)
    if _integer(result, "winning_trades") != winning:
        raise RuntimeError(f"{lane.name}: winning_trades mismatch")
    if _integer(result, "losing_trades") != losing:
        raise RuntimeError(f"{lane.name}: losing_trades mismatch")
    if _integer(result, "breakeven_trades") != breakeven:
        raise RuntimeError(f"{lane.name}: breakeven_trades mismatch")
    equity = 1.0
    for value in trade_returns:
        equity *= 1.0 + value
    try:
        total_return = float(result["total_return"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{lane.name}: total_return must be numeric") from exc
    if not isfinite(total_return) or not isclose(total_return, equity - 1.0, rel_tol=1e-12, abs_tol=1e-12):
        raise RuntimeError(f"{lane.name}: total_return mismatch")
    if _integer(result, "held_source_bars") < lane.hold_source_bars:
        raise RuntimeError(f"{lane.name}: held_source_bars below minimum")
    if _integer(result, "reconciliation_errors") != 0:
        raise RuntimeError(f"{lane.name}: reconciliation_errors must be zero")
    if not _boolean(result, "final_flat"):
        raise RuntimeError(f"{lane.name}: final_flat must be true")

    sides_raw = result.get("observed_sides")
    if not isinstance(sides_raw, list) or not all(isinstance(value, str) for value in sides_raw):
        raise RuntimeError(f"{lane.name}: observed_sides must be a string list")
    required_sides = [action for action in lane.plan if action in {"LONG", "SHORT"}]
    cursor = 0
    for observed in sides_raw:
        if cursor < len(required_sides) and observed == required_sides[cursor]:
            cursor += 1
    if cursor != len(required_sides):
        raise RuntimeError(f"{lane.name}: observed_sides did not prove the requested path")


def _write_receipt(path: str | Path, result: Mapping[str, object]) -> None:
    receipt_path = Path(path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = receipt_path.with_name(f".{receipt_path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(dict(result), handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, receipt_path)


_TIMEFRAME_COMPONENTS = {
    "1m": "1-MINUTE",
    "3m": "3-MINUTE",
    "5m": "5-MINUTE",
}
_TIMEFRAME_SECONDS = {"1m": 60.0, "3m": 180.0, "5m": 300.0}


def _default_lane_deadline_seconds(lane: ExecutionCanaryLane) -> float:
    try:
        source_seconds = _TIMEFRAME_SECONDS[lane.source_timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported execution-canary timeframe: {lane.source_timeframe}") from exc
    required_market_seconds = float(lane.minimum_real_closed_bars) * source_seconds
    return max(360.0, required_market_seconds + 180.0)


class _PaperExecutionCanaryStrategyConfig:
    pass


def _build_canary_strategy(*, lane: ExecutionCanaryLane, instrument, risk_runtime: RiskRuntime):
    from nautilus_trader.config import StrategyConfig
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.trading.strategy import Strategy

    from .nautilus_risk_hook import NautilusRiskMixin

    try:
        timeframe_component = _TIMEFRAME_COMPONENTS[lane.source_timeframe]
    except KeyError as exc:
        raise ValueError(f"unsupported execution-canary timeframe: {lane.source_timeframe}") from exc

    class CanaryConfig(StrategyConfig):
        instrument_id: object
        bar_type: object
        trade_size: Decimal
        lane_name: str

    config = CanaryConfig(
        instrument_id=instrument.id,
        bar_type=BarType.from_str(
            f"{instrument.id.value}-{timeframe_component}-LAST-EXTERNAL"
        ),
        trade_size=Decimal("0.001"),
        lane_name=lane.name,
    )

    class CanaryStrategy(NautilusRiskMixin, Strategy):
        def __init__(self, *, config, lane: ExecutionCanaryLane, risk_runtime: RiskRuntime):
            super().__init__(config)
            self.lane = lane
            self.instrument = None
            self.real_closed_bars = 0
            self.held_source_bars = 0
            self.closed_positions = 0
            self.closed_trade_returns: list[float] = []
            self.observed_sides: list[str] = []
            self._position_side = "FLAT"
            self._cursor = 0
            self._done = False
            self._last_price = 0.0
            self._armed = False
            self._configure_risk_runtime(f"TEST-ONLY:{lane.name}", risk_runtime)

        @property
        def done(self) -> bool:
            return self._done

        def arm(self) -> None:
            self._armed = True

        def on_start(self) -> None:
            self.instrument = self.cache.instrument(self.config.instrument_id)
            if self.instrument is None:
                raise RuntimeError("execution canary instrument is unavailable")
            self.subscribe_bars(self.config.bar_type)

        def _risk_reference_price(self, instrument_id) -> float:
            del instrument_id
            return self._last_price

        def _matches(self, event) -> bool:
            return getattr(event, "instrument_id", None) == self.config.instrument_id

        @staticmethod
        def _event_side(event) -> str:
            side = getattr(event, "side", None)
            name = getattr(side, "name", str(side)).upper()
            if name.endswith("LONG"):
                return "LONG"
            if name.endswith("SHORT"):
                return "SHORT"
            return "FLAT"

        def on_position_opened(self, event) -> None:
            if not self._matches(event):
                return
            side = self._event_side(event)
            if side not in {"LONG", "SHORT"}:
                raise RuntimeError("execution canary opened a position without a side")
            self._position_side = side
            if not self.observed_sides or self.observed_sides[-1] != side:
                self.observed_sides.append(side)
            if self._cursor < len(self.lane.plan) and self.lane.plan[self._cursor] == side:
                self._cursor += 1

        def on_position_changed(self, event) -> None:
            if not self._matches(event):
                return
            side = self._event_side(event)
            if side in {"LONG", "SHORT"}:
                self._position_side = side
                if not self.observed_sides or self.observed_sides[-1] != side:
                    self.observed_sides.append(side)
                if self._cursor < len(self.lane.plan) and self.lane.plan[self._cursor] == side:
                    self._cursor += 1

        def on_position_closed(self, event) -> None:
            if not self._matches(event):
                return
            self.closed_positions += 1
            self.closed_trade_returns.append(float(event.realized_return))
            self._position_side = "FLAT"
            if self._cursor < len(self.lane.plan) and self.lane.plan[self._cursor] == "FLAT":
                self._cursor += 1
                self._done = self._cursor == len(self.lane.plan)

        def _canary_order_quantity(self):
            if self.instrument is None:
                raise RuntimeError("execution canary instrument is unavailable")
            if self._last_price <= 0.0:
                raise RuntimeError("execution canary reference price is unavailable")

            configured = Decimal(self.config.trade_size)
            minimum_notional = getattr(self.instrument, "min_notional", None)
            if minimum_notional is None:
                return self.instrument.make_qty(configured)

            # This TEST-ONLY canary must exercise the venue's genuine order
            # validation path. Size just above minimum notional rather than
            # weakening validation or hard-coding a quantity which can stale.
            notional_floor = Decimal(minimum_notional.as_decimal()) * Decimal("1.05")
            required = notional_floor / Decimal(str(self._last_price))
            target = max(configured, required)
            increment = Decimal(self.instrument.size_increment.as_decimal())
            steps = (target / increment).to_integral_value(rounding=ROUND_CEILING)
            return self.instrument.make_qty(steps * increment)

        def _submit_side(self, side: str) -> None:
            if self.instrument is None:
                raise RuntimeError("execution canary instrument is unavailable")
            order_side = OrderSide.BUY if side == "LONG" else OrderSide.SELL
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=order_side,
                quantity=self._canary_order_quantity(),
            )
            self.submit_order(order)

        def _drive_plan(self) -> None:
            while self._cursor < len(self.lane.plan):
                action = self.lane.plan[self._cursor]
                if action == "HOLD":
                    if self._position_side == "FLAT":
                        raise RuntimeError("execution canary cannot HOLD while flat")
                    self.held_source_bars += 1
                    self._cursor += 1
                    return

                if action == "LONG":
                    if self._position_side == "LONG":
                        self._cursor += 1
                        return
                    if self._position_side == "SHORT":
                        self.close_all_positions(self.config.instrument_id)
                        return
                    self._submit_side("LONG")
                    return

                if action == "SHORT":
                    if self._position_side == "SHORT":
                        self._cursor += 1
                        return
                    if self._position_side == "LONG":
                        self.close_all_positions(self.config.instrument_id)
                        return
                    self._submit_side("SHORT")
                    return

                if action == "FLAT":
                    if self._position_side == "FLAT":
                        self._cursor += 1
                        self._done = self._cursor == len(self.lane.plan)
                        return
                    self.close_all_positions(self.config.instrument_id)
                    return

                raise RuntimeError(f"unsupported execution canary action: {action}")

        def on_bar(self, bar) -> None:
            if bar.bar_type != self.config.bar_type:
                return
            self._last_price = float(bar.close.as_double())
            if not self._armed:
                return
            self.real_closed_bars += 1
            self._drive_plan()

        def on_stop(self) -> None:
            if self.instrument is not None and not self.portfolio.is_flat(self.config.instrument_id):
                self.close_all_positions(self.config.instrument_id)

    return CanaryStrategy(config=config, lane=lane, risk_runtime=risk_runtime)


class _CanaryPaperBridge:
    def __init__(
        self,
        *,
        lane: ExecutionCanaryLane,
        instrument,
        bootstrap_bar,
        risk_runtime: RiskRuntime,
    ) -> None:
        from .nautilus_backtest import _build_binance_spot_engine

        base = str(instrument.base_currency)
        quote = str(instrument.quote_currency)
        self._engine = _build_binance_spot_engine(
            instrument=instrument,
            starting_balances=(f"10 {base}", f"100000 {quote}"),
        )
        self._instrument = instrument
        self.strategy = _build_canary_strategy(
            lane=lane,
            instrument=instrument,
            risk_runtime=risk_runtime,
        )
        self._engine.add_strategy(self.strategy)
        bootstrap_close_ms = int(
            bootstrap_bar.extras.get(
                "source_kline_close_ms",
                int(bootstrap_bar.timestamp.timestamp() * 1_000),
            ),
        )
        bootstrap_event = MarketStreamEvent(
            event_id=f"bootstrap-{lane.name}",
            data=bootstrap_bar,
            timestamp_ns=bootstrap_close_ms * 1_000_000,
        )
        self._engine.add_data([self._bar(bootstrap_event)])
        self._engine.run(streaming=True)
        self._engine.clear_data()
        self.strategy.arm()
        self._closed = False

    def _bar(self, event: MarketStreamEvent):
        from nautilus_trader.model.data import Bar
        from nautilus_trader.model.objects import Price, Quantity

        bar = event.bar
        price_precision = int(self._instrument.price_precision)
        size_precision = int(self._instrument.size_precision)
        return Bar(
            bar_type=self.strategy.config.bar_type,
            open=Price.from_str(f"{float(bar.open):.{price_precision}f}"),
            high=Price.from_str(f"{float(bar.high):.{price_precision}f}"),
            low=Price.from_str(f"{float(bar.low):.{price_precision}f}"),
            close=Price.from_str(f"{float(bar.close):.{price_precision}f}"),
            volume=Quantity.from_str(f"{float(bar.volume):.{size_precision}f}"),
            ts_event=event.timestamp_ns,
            ts_init=event.timestamp_ns,
        )

    def _quote(self, event: MarketStreamEvent):
        from nautilus_trader.model.data import QuoteTick
        from nautilus_trader.model.objects import Price, Quantity

        tick = event.tick
        price_precision = int(self._instrument.price_precision)
        size_precision = int(self._instrument.size_precision)
        return QuoteTick(
            instrument_id=self._instrument.id,
            bid_price=Price.from_str(f"{float(tick.bid):.{price_precision}f}"),
            ask_price=Price.from_str(f"{float(tick.ask):.{price_precision}f}"),
            bid_size=Quantity.from_str(f"{float(tick.bid_size):.{size_precision}f}"),
            ask_size=Quantity.from_str(f"{float(tick.ask_size):.{size_precision}f}"),
            ts_event=event.timestamp_ns,
            ts_init=event.timestamp_ns,
        )

    def dispatch(self, event: MarketStreamEvent) -> None:
        data = self._bar(event) if event.kind == "bar" else self._quote(event)
        self._engine.add_data([data])
        self._engine.run(streaming=True)
        self._engine.clear_data()

    def closed_trade_returns(self) -> list[float]:
        return list(self.strategy.closed_trade_returns)

    def execution_state(self, *, account_id: str) -> ExecutionState:
        from nautilus_trader.model.identifiers import Venue

        positions: dict[str, object] = {}
        for position in self._engine.cache.positions_open(strategy_id=self.strategy.id):
            instrument_id = position.instrument_id.value
            positions[instrument_id] = positions.get(instrument_id, 0) + position.signed_decimal_qty()
        open_order_ids = frozenset(
            order.client_order_id.value
            for order in self._engine.cache.orders_open(strategy_id=self.strategy.id)
        )
        account = self._engine.cache.account_for_venue(Venue("BINANCE"))
        if account is None:
            raise RuntimeError("execution canary account state is unavailable")
        balances = {
            str(currency): money.as_decimal()
            for currency, money in account.balances_total().items()
        }
        return ExecutionState(
            account_id=account_id,
            positions=positions,
            open_order_ids=open_order_ids,
            balances=balances,
        )

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._engine.end()
        finally:
            self._engine.dispose()
            self._closed = True


InstrumentLoader = Callable[[str], object]
HistoryLoader = Callable[..., Sequence[object]]
SourceFactory = Callable[..., object]


def _coalesced_canary_stream(source):
    """Bound quote replay while preserving risk/reconciliation heartbeats.

    The Binance source still consumes every public book update so completeness
    recovery and quote-derived metadata remain authoritative. Nautilus receives
    the latest real quote before each closed bar plus a real quote heartbeat at
    most 30 seconds apart, keeping the strict 60-second reconciliation-age gate
    healthy without replaying thousands of intermediate quotes.
    """
    heartbeat_ns = 30_000_000_000
    latest_tick: MarketStreamEvent | None = None
    heartbeat_anchor_ns: int | None = None
    for raw in source:
        event = raw if isinstance(raw, MarketStreamEvent) else MarketStream.normalize(raw)
        if event.kind == "tick":
            latest_tick = event
            if heartbeat_anchor_ns is None:
                heartbeat_anchor_ns = event.timestamp_ns
            elif event.timestamp_ns - heartbeat_anchor_ns >= heartbeat_ns:
                yield event
                heartbeat_anchor_ns = event.timestamp_ns
                latest_tick = None
            continue
        if latest_tick is not None and latest_tick.timestamp_ns <= event.timestamp_ns:
            yield latest_tick
            heartbeat_anchor_ns = latest_tick.timestamp_ns
            latest_tick = None
        yield event


def run_paper_execution_canary_lane(
    lane: ExecutionCanaryLane,
    *,
    instrument_loader: InstrumentLoader = load_public_binance_spot_instrument,
    history_loader: HistoryLoader = load_public_binance_bar_history,
    source_factory: SourceFactory = BinancePublicMarketSource,
    code_hash: str | None = None,
    deadline_seconds: float | None = None,
    risk_monotonic_clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    symbol = "ETHUSDT.BINANCE"
    instrument = instrument_loader(symbol)
    history = history_loader(symbol, lane.source_timeframe, limit=2)
    first_expected_start_ms = _public_paper_first_expected_start_ms(
        history,
        timeframe=lane.source_timeframe,
    )
    source = source_factory(
        (symbol,),
        timeframe=lane.source_timeframe,
        first_expected_start_ms=first_expected_start_ms,
        recovery_grace_ms=3_000,
        reconnect_backoff_seconds=(1.0, 2.0, 5.0),
        max_reconnect_attempts=20,
    )

    provider = RiskStateProvider()
    provider.update_account_state(
        symbol=symbol,
        portfolio_id="default",
        symbol_exposure=0.0,
        portfolio_exposure=0.0,
        daily_pnl=0.0,
        drawdown=0.0,
        leverage=0.0,
        correlated_exposure=0.0,
    )
    risk_runtime = RiskRuntime(
        _paper_risk_limits(),
        monotonic_clock=risk_monotonic_clock or time.monotonic,
        state_provider=provider,
    )
    risk_runtime.update_api_health(
        venue="BINANCE",
        healthy=True,
        error_rate=0.0,
        latency_ms=0.0,
    )

    bridge = _CanaryPaperBridge(
        lane=lane,
        instrument=instrument,
        bootstrap_bar=history[-1],
        risk_runtime=risk_runtime,
    )
    effective_code_hash = code_hash or os.environ.get("GITHUB_SHA") or "TEST-ONLY-PAPER-EXECUTION-CANARY"
    lane_payload = json.dumps(
        {
            "lane": lane.name,
            "source_timeframe": lane.source_timeframe,
            "target_minutes": lane.target_minutes,
            "plan": lane.plan,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    genome_hash = hashlib.sha256(lane_payload.encode()).hexdigest()
    session_id = hashlib.sha256(f"{effective_code_hash}:{genome_hash}".encode()).hexdigest()[:24]
    receipt = PaperStartReceipt(
        strategy_id=f"TEST-ONLY:{lane.name}",
        genome_hash=genome_hash,
        session_id=session_id,
        venue="SANDBOX",
        engine="nautilus_trader",
        engine_version=version("nautilus_trader"),
        connected=True,
    )

    if deadline_seconds is None:
        deadline_seconds = _default_lane_deadline_seconds(lane)
    if deadline_seconds <= 0.0:
        raise ValueError("deadline_seconds must be positive")

    with tempfile.TemporaryDirectory(prefix=f"mastertrd-{lane.name}-") as temp_dir:
        store = JsonPaperSessionStore(Path(temp_dir) / "session.json")
        journal = PaperSessionJournal(
            receipt,
            code_hash=effective_code_hash,
            started_ns=time.time_ns(),
        )
        store.save(journal)
        account_id = f"paper-canary:{session_id}"
        state = lambda: bridge.execution_state(account_id=account_id)
        runtime = ExecutionRuntime(
            journal=journal,
            session_store=store,
            risk_runtime=risk_runtime,
            reconciler=Reconciler(),
            engine_state=state,
            venue_state=state,
            dispatch=bridge.dispatch,
            stream=MarketStream(_coalesced_canary_stream(source)),
            finalizer=bridge.close,
        )
        started = time.monotonic()
        timed_out = False

        def stop_requested() -> bool:
            nonlocal timed_out
            if bridge.strategy.done:
                return True
            if time.monotonic() - started >= float(deadline_seconds):
                timed_out = True
                return True
            return False

        try:
            run_report = runtime.run(stop_requested=stop_requested)
            if timed_out:
                raise RuntimeError("execution canary deadline reached before the lane completed")
            if not bridge.strategy.done:
                raise RuntimeError("execution canary market stream ended before the lane completed")
            final_state = state()
            snapshot = getattr(source, "completeness_snapshot", None)
            if snapshot is None:
                raise RuntimeError("execution canary completeness snapshot is unavailable")
            risk = bridge.strategy.risk_telemetry()
            trade_returns = bridge.closed_trade_returns()
            equity = 1.0
            for value in trade_returns:
                equity *= 1.0 + value
            final_flat = not final_state.open_order_ids and all(
                quantity == 0 for quantity in final_state.positions.values()
            )
            result = {
                "lane": lane.name,
                "source_timeframe": lane.source_timeframe,
                "target_minutes": lane.target_minutes,
                "plan": list(lane.plan),
                "real_closed_bars": int(bridge.strategy.real_closed_bars),
                "data_healthy": bool(snapshot.data_healthy),
                "missing_closed_bars": int(snapshot.missing_closed_bars),
                "recovery_failures": int(snapshot.recovery_failures),
                "orders_attempted": int(risk["orders_attempted"]),
                "orders_allowed": int(risk["orders_allowed"]),
                "orders_rejected": int(risk["orders_rejected"]),
                "observed_sides": list(bridge.strategy.observed_sides),
                "closed_positions": int(bridge.strategy.closed_positions),
                "closed_trade_returns": trade_returns,
                "winning_trades": sum(1 for value in trade_returns if value > 0.0),
                "losing_trades": sum(1 for value in trade_returns if value < 0.0),
                "breakeven_trades": sum(1 for value in trade_returns if value == 0.0),
                "total_return": equity - 1.0,
                "held_source_bars": int(bridge.strategy.held_source_bars),
                "reconciliation_errors": int(run_report.reconciliation_errors),
                "reconciliation_checks": int(run_report.reconciliation_checks),
                "processed_events": int(run_report.processed_events),
                "final_flat": bool(final_flat),
                "mode": "PAPER",
                "live_enabled": False,
                "test_only": True,
                "counts_as_alpha": False,
                "live_eligible": False,
                "code_hash": effective_code_hash,
                "strategy_id": receipt.strategy_id,
                "genome_hash": genome_hash,
                "expected_closed_bars": int(snapshot.expected_closed_bars),
                "ws_closed_bars": int(snapshot.ws_closed_bars),
                "rest_recovered_bars": int(snapshot.rest_recovered_bars),
            }
            validate_execution_canary_result(lane, result)
            return result
        finally:
            runtime.close()


LaneRunner = Callable[[ExecutionCanaryLane], dict[str, object]]


def run_paper_execution_canary_matrix(
    *,
    lane_runner: LaneRunner = run_paper_execution_canary_lane,
    receipt_path: str | Path | None = None,
    max_workers: int = 4,
) -> dict[str, object]:
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        raise TypeError("max_workers must be an integer")
    if max_workers <= 0:
        raise ValueError("max_workers must be positive")

    lanes = execution_canary_lanes()
    results: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(lanes))) as pool:
        futures = {pool.submit(lane_runner, lane): lane for lane in lanes}
        for future in as_completed(futures):
            lane = futures[future]
            try:
                result = future.result()
                validate_execution_canary_result(lane, result)
            except Exception as exc:
                for pending in futures:
                    pending.cancel()
                raise RuntimeError(f"{lane.name}: PAPER execution canary failed: {exc}") from exc
            results[lane.name] = dict(result)

    ordered = [results[lane.name] for lane in lanes]
    aggregate: dict[str, Any] = {
        "mode": "PAPER",
        "live_enabled": False,
        "test_only": True,
        "counts_as_alpha": False,
        "live_eligible": False,
        "all_passed": True,
        "lanes": ordered,
    }
    if receipt_path is not None:
        _write_receipt(receipt_path, aggregate)
    return aggregate


if __name__ == "__main__":
    receipt_path = os.environ.get(
        "MASTERTRD_EXECUTION_CANARY_RECEIPT",
        "paper-execution-canary-receipt.json",
    )
    print(json.dumps(run_paper_execution_canary_matrix(receipt_path=receipt_path), sort_keys=True))
