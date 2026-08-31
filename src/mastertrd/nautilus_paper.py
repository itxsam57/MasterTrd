from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
from pathlib import Path

from .genome import StrategyGenome
from .paper_evidence import PaperStartReceipt
from .paper_events import NautilusPaperEventSink
from .paper_session import JsonPaperSessionStore, PaperSessionJournal
from .reconciliation import ExecutionState
from .risk_runtime import RiskRuntime
from .streaming import MarketStreamEvent


@dataclass(frozen=True, slots=True)
class PersistentPaperSession:
    journal: PaperSessionJournal
    store: JsonPaperSessionStore
    resumed: bool


def probe_nautilus_sandbox_session(
    candidate: StrategyGenome,
    *,
    session_nonce: str = "default-session",
) -> PaperStartReceipt:
    if not session_nonce:
        raise ValueError("session_nonce is required")

    from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
    from nautilus_trader.adapters.sandbox.execution import SandboxExecutionClient
    from nautilus_trader.common.component import MessageBus, TestClock
    from nautilus_trader.portfolio.portfolio import Portfolio
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs
    from nautilus_trader.test_kit.stubs.identifiers import TestIdStubs

    engine_version = version("nautilus_trader")
    venue = "SANDBOX"
    session_id = hashlib.sha256(
        f"{candidate.strategy_id}:{candidate.genome_hash}:{venue}:{engine_version}:{session_nonce}".encode()
    ).hexdigest()[:24]

    loop = asyncio.new_event_loop()
    client = None
    try:
        clock = TestClock()
        clock.set_time(0)
        msgbus = MessageBus(TestIdStubs.trader_id(), clock)
        cache = TestComponentStubs.cache()
        instrument = TestInstrumentProvider.equity("AAPL", venue)
        cache.add_instrument(instrument)
        portfolio = Portfolio(msgbus, cache, clock)
        config = SandboxExecutionClientConfig(
            venue=venue,
            starting_balances=["100_000 USD"],
            base_currency="USD",
            account_type="CASH",
        )
        client = SandboxExecutionClient(
            loop=loop,
            portfolio=portfolio,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        client.connect()
        connected = bool(client.is_connected)
        return PaperStartReceipt(
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            session_id=session_id,
            venue=venue,
            engine="nautilus_trader",
            engine_version=engine_version,
            connected=connected,
        )
    finally:
        if client is not None and client.is_connected:
            client.disconnect()
        loop.close()


def open_persistent_paper_session(
    candidate: StrategyGenome,
    *,
    state_path: str | Path,
    code_hash: str,
    started_ns: int | None = None,
    session_nonce: str = "default-session",
    resume: bool = False,
) -> PersistentPaperSession:
    if not code_hash:
        raise ValueError("code_hash is required")
    path = Path(state_path)
    store = JsonPaperSessionStore(path)

    if resume:
        journal = store.load()
        if journal.strategy_id != candidate.strategy_id:
            raise ValueError("strategy_id does not match persisted paper session")
        if journal.genome_hash != candidate.genome_hash:
            raise ValueError("genome_hash does not match persisted paper session")
        if journal.code_hash != code_hash:
            raise ValueError("code_hash does not match persisted paper session")
        return PersistentPaperSession(journal=journal, store=store, resumed=True)

    if started_ns is None:
        raise ValueError("started_ns is required for a new paper session")
    if path.exists():
        raise ValueError("paper session state already exists; use resume=True")

    receipt = probe_nautilus_sandbox_session(candidate, session_nonce=session_nonce)
    journal = PaperSessionJournal(receipt, code_hash=code_hash, started_ns=int(started_ns))
    store.save(journal)
    return PersistentPaperSession(journal=journal, store=store, resumed=False)


def fixture_binance_spot_instrument(instrument_id: str):
    """Return pinned Nautilus metadata for deterministic recorded-feed fixtures.

    This helper is deliberately limited to the checked-in fixture universe. Real
    public-network PAPER must load exchange metadata through the Binance adapter
    rather than guessing tick/size precision.
    """

    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    providers = {
        "ETHUSDT.BINANCE": TestInstrumentProvider.ethusdt_binance,
        "BTCUSDT.BINANCE": TestInstrumentProvider.btcusdt_binance,
    }
    try:
        provider = providers[instrument_id]
    except KeyError as exc:
        raise RuntimeError(
            f"no deterministic Binance instrument fixture is registered for {instrument_id}"
        ) from exc
    return provider()


def _build_public_binance_spot_provider():
    """Build Nautilus's credential-free LIVE spot instrument provider.

    Binance exchange-info is public. Explicit ``None`` credentials ensure this
    path cannot accidentally authenticate or depend on account secrets while it
    loads the venue's current price/size precision and trading filters.
    """

    from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
    from nautilus_trader.adapters.binance.common.enums import BinanceEnvironment
    from nautilus_trader.adapters.binance.factories import get_cached_binance_http_client
    from nautilus_trader.adapters.binance.spot.providers import BinanceSpotInstrumentProvider
    from nautilus_trader.common.component import LiveClock

    clock = LiveClock()
    account_type = BinanceAccountType.SPOT
    environment = BinanceEnvironment.LIVE
    client = get_cached_binance_http_client(
        clock=clock,
        account_type=account_type,
        api_key=None,
        api_secret=None,
        environment=environment,
    )
    return BinanceSpotInstrumentProvider(
        client=client,
        clock=clock,
        account_type=account_type,
        environment=environment,
    )


def load_public_binance_spot_instrument(instrument_id: str):
    """Load exact current Binance spot metadata without credentials.

    The loader intentionally fails closed if the candidate is not a Binance
    instrument, the public exchange-info request fails, or Nautilus cannot
    resolve the requested identity after loading it. There is no fallback to
    deterministic test-kit metadata on the public PAPER path.
    """

    from nautilus_trader.model.identifiers import InstrumentId

    try:
        requested = InstrumentId.from_str(instrument_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("public Binance instrument identity is invalid") from exc
    if str(requested.venue) != "BINANCE":
        raise RuntimeError("public PAPER instrument must use the BINANCE venue")

    provider = _build_public_binance_spot_provider()
    try:
        asyncio.run(provider.load_async(requested))
    except Exception as exc:
        raise RuntimeError("public Binance instrument metadata could not be loaded") from exc

    instrument = provider.find(requested)
    if instrument is None:
        raise RuntimeError(f"public Binance instrument metadata not found for {instrument_id}")
    if instrument.id != requested:
        raise RuntimeError("public Binance instrument metadata identity mismatch")
    return instrument


class NautilusStreamingPaperExecution:
    """Route one normalized market event at a time through Nautilus execution.

    The low-level Nautilus BacktestEngine streaming mode is used here as the
    deterministic sandbox execution kernel. It preserves strategy/execution
    state between batches while allowing MasterTrd to reconcile and persist its
    journal after every source event. Order matching and PositionClosed events
    remain Nautilus-owned.
    """

    def __init__(
        self,
        *,
        candidate: StrategyGenome,
        risk_runtime: RiskRuntime,
        journal: PaperSessionJournal,
        instrument,
    ) -> None:
        if len(candidate.instruments) != 1:
            raise RuntimeError("streaming PAPER bridge currently requires one instrument")
        if instrument.id.value != candidate.instruments[0]:
            raise ValueError("paper instrument does not match candidate identity")

        from .nautilus_backtest import _build_binance_spot_engine
        from .nautilus_strategy import compile_genome_to_nautilus

        base_code = str(instrument.base_currency)
        quote_code = str(instrument.quote_currency)
        self._engine = _build_binance_spot_engine(
            instrument=instrument,
            starting_balances=(f"10 {base_code}", f"100000 {quote_code}"),
        )
        self._instrument = instrument
        self._sink = NautilusPaperEventSink(journal)
        self._ended = False

        compiled = compile_genome_to_nautilus(
            candidate,
            instrument=instrument,
            risk_runtime=risk_runtime,
        )
        strategy_type = type(compiled)
        sink = self._sink

        class RecordingStrategy(strategy_type):
            def on_position_closed(self, event):
                sink.on_position_closed(event)
                parent = getattr(super(), "on_position_closed", None)
                if parent is not None:
                    parent(event)

        self._strategy = RecordingStrategy(
            config=compiled.config,
            genome=candidate,
            risk_runtime=risk_runtime,
        )
        self._engine.add_strategy(self._strategy)

    @property
    def closed_positions(self) -> int:
        return self._sink.closed_positions

    def execution_state(self, *, account_id: str) -> ExecutionState:
        """Snapshot the current Nautilus sandbox account/cache for reconciliation."""
        if not account_id:
            raise ValueError("account_id is required")

        from nautilus_trader.model.identifiers import Venue

        positions: dict[str, object] = {}
        for position in self._engine.cache.positions_open(strategy_id=self._strategy.id):
            instrument_id = position.instrument_id.value
            positions[instrument_id] = positions.get(instrument_id, 0) + position.signed_decimal_qty()

        open_order_ids = frozenset(
            order.client_order_id.value
            for order in self._engine.cache.orders_open(strategy_id=self._strategy.id)
        )

        account = self._engine.cache.account_for_venue(Venue("BINANCE"))
        if account is None:
            raise RuntimeError("Nautilus PAPER account state is unavailable")
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

    def _bar(self, event: MarketStreamEvent):
        from nautilus_trader.model.data import Bar
        from nautilus_trader.model.objects import Price, Quantity

        bar = event.bar
        price_precision = int(self._instrument.price_precision)
        size_precision = int(self._instrument.size_precision)

        def price(value: float) -> Price:
            return Price.from_str(f"{float(value):.{price_precision}f}")

        def quantity(value: float) -> Quantity:
            return Quantity.from_str(f"{float(value):.{size_precision}f}")

        return Bar(
            bar_type=self._strategy.config.bar_type,
            open=price(bar.open),
            high=price(bar.high),
            low=price(bar.low),
            close=price(bar.close),
            volume=quantity(bar.volume),
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
        if self._ended:
            raise RuntimeError("Nautilus PAPER execution bridge is already finalized")
        data = self._bar(event) if event.kind == "bar" else self._quote(event)
        self._engine.add_data([data])
        self._engine.run(streaming=True)
        self._engine.clear_data()

    def close(self) -> None:
        if self._ended:
            return
        try:
            self._engine.end()
        finally:
            self._engine.dispose()
            self._ended = True
