from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from importlib.metadata import version

from .contracts import MarketBar
from .genome import StrategyGenome
from .paper_evidence import PaperStartReceipt
from .paper_events import NautilusPaperEventSink
from .paper_session import PaperSessionJournal
from .reconciliation import ExecutionState
from .risk_state import RiskStateProvider
from .risk_runtime import RiskRuntime
from .streaming import MarketStreamEvent


class PaperPortfolioJournal:
    def __init__(
        self,
        portfolio_id: str,
        journals: Mapping[str, PaperSessionJournal],
    ) -> None:
        if not portfolio_id:
            raise ValueError("portfolio_id is required")
        normalized = dict(journals)
        if len(normalized) < 2:
            raise ValueError("paper portfolio requires at least two strategies")
        if set(normalized) != {journal.strategy_id for journal in normalized.values()}:
            raise ValueError("paper portfolio journal identity mismatch")
        code_hashes = {journal.code_hash for journal in normalized.values()}
        if len(code_hashes) != 1:
            raise ValueError("paper portfolio journals must share one code identity")
        self.portfolio_id = portfolio_id
        self._journals = normalized

    @property
    def strategy_ids(self) -> tuple[str, ...]:
        return tuple(self._journals)

    @property
    def code_hash(self) -> str:
        return next(iter(self._journals.values())).code_hash

    @property
    def started_ns(self) -> int:
        return min(journal.started_ns for journal in self._journals.values())

    @property
    def latest_timestamp_ns(self) -> int:
        return max(journal.latest_timestamp_ns for journal in self._journals.values())

    @property
    def execution_state_checkpoint(self) -> ExecutionState | None:
        checkpoints = [journal.execution_state_checkpoint for journal in self._journals.values()]
        present = [state for state in checkpoints if state is not None]
        if not present:
            return None
        if len(present) != len(checkpoints) or any(state != present[0] for state in present[1:]):
            raise RuntimeError("paper portfolio execution checkpoints disagree")
        return present[0]

    def journal(self, strategy_id: str) -> PaperSessionJournal:
        try:
            return self._journals[strategy_id]
        except KeyError as exc:
            raise ValueError(f"unknown portfolio strategy: {strategy_id}") from exc

    def has_event(self, event_id: str) -> bool:
        observed = [journal.has_event(event_id) for journal in self._journals.values()]
        if any(observed) and not all(observed):
            raise RuntimeError("paper portfolio event durability is inconsistent")
        return all(observed)

    def record_market_event(self, event_id: str, *, timestamp_ns: int) -> None:
        for journal in self._journals.values():
            journal.record_market_event(event_id, timestamp_ns=timestamp_ns)

    def record_reconciliation(self, check_id: str, *, ok: bool, timestamp_ns: int) -> None:
        for journal in self._journals.values():
            journal.record_reconciliation(check_id, ok=ok, timestamp_ns=timestamp_ns)

    def record_execution_state(self, state: ExecutionState, *, timestamp_ns: int) -> None:
        for journal in self._journals.values():
            journal.record_execution_state(state, timestamp_ns=timestamp_ns)

    def persistence_payload(self) -> dict[str, object]:
        return {
            "portfolio_id": self.portfolio_id,
            "journals": {
                strategy_id: journal._persistence_payload()
                for strategy_id, journal in sorted(self._journals.items())
            },
        }

    @classmethod
    def restore(cls, payload: Mapping[str, object]) -> "PaperPortfolioJournal":
        portfolio_id = payload.get("portfolio_id")
        journals_raw = payload.get("journals")
        if not isinstance(portfolio_id, str) or not portfolio_id or not isinstance(journals_raw, dict):
            raise ValueError("paper portfolio state is invalid")
        journals: dict[str, PaperSessionJournal] = {}
        for strategy_id, raw in journals_raw.items():
            if not isinstance(strategy_id, str) or not isinstance(raw, dict):
                raise ValueError("paper portfolio state is invalid")
            journal = PaperSessionJournal._restore(raw)
            if journal.strategy_id != strategy_id:
                raise ValueError("paper portfolio strategy identity mismatch")
            journals[strategy_id] = journal
        return cls(portfolio_id, journals)


class JsonPaperPortfolioStore:
    VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @staticmethod
    def _hash(payload: Mapping[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def save(self, journal: PaperPortfolioJournal) -> None:
        payload = journal.persistence_payload()
        envelope = {
            "version": self.VERSION,
            "payload": payload,
            "state_hash": self._hash(payload),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(envelope, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    def load(self) -> PaperPortfolioJournal:
        try:
            envelope = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("paper portfolio state integrity check failed") from exc
        if not isinstance(envelope, dict) or envelope.get("version") != self.VERSION:
            raise ValueError("paper portfolio state integrity check failed")
        payload = envelope.get("payload")
        state_hash = envelope.get("state_hash")
        if not isinstance(payload, dict) or not isinstance(state_hash, str):
            raise ValueError("paper portfolio state integrity check failed")
        if self._hash(payload) != state_hash:
            raise ValueError("paper portfolio state integrity check failed")
        return PaperPortfolioJournal.restore(payload)


@dataclass(frozen=True, slots=True)
class PersistentPaperPortfolio:
    journal: PaperPortfolioJournal
    store: JsonPaperPortfolioStore
    resumed: bool


def open_paper_portfolio(
    candidates: Sequence[StrategyGenome],
    *,
    portfolio_id: str,
    state_path: str | Path,
    code_hash: str,
    started_ns: int,
    session_nonce: str = "portfolio-paper",
    resume: bool = False,
) -> PersistentPaperPortfolio:
    candidates = tuple(candidates)
    if len(candidates) < 2:
        raise ValueError("paper portfolio requires at least two candidates")
    if len({candidate.strategy_id for candidate in candidates}) != len(candidates):
        raise ValueError("paper portfolio strategy identities must be unique")
    if not code_hash:
        raise ValueError("code_hash is required")
    store = JsonPaperPortfolioStore(state_path)

    if resume:
        journal = store.load()
        if journal.portfolio_id != portfolio_id or journal.code_hash != code_hash:
            raise ValueError("paper portfolio identity does not match persisted state")
        expected = {candidate.strategy_id: candidate.genome_hash for candidate in candidates}
        actual = {
            strategy_id: journal.journal(strategy_id).genome_hash
            for strategy_id in journal.strategy_ids
        }
        if expected != actual:
            raise ValueError("paper portfolio candidate set does not match persisted state")
        return PersistentPaperPortfolio(journal=journal, store=store, resumed=True)

    if Path(state_path).exists():
        raise ValueError("paper portfolio state already exists; use resume=True")
    engine_version = version("nautilus_trader")
    journals: dict[str, PaperSessionJournal] = {}
    for candidate in candidates:
        session_id = hashlib.sha256(
            f"{portfolio_id}:{candidate.strategy_id}:{candidate.genome_hash}:{code_hash}:{session_nonce}".encode()
        ).hexdigest()[:24]
        receipt = PaperStartReceipt(
            strategy_id=candidate.strategy_id,
            genome_hash=candidate.genome_hash,
            session_id=session_id,
            venue="SANDBOX",
            engine="nautilus_trader",
            engine_version=engine_version,
            connected=True,
        )
        journals[candidate.strategy_id] = PaperSessionJournal(
            receipt,
            code_hash=code_hash,
            started_ns=started_ns,
        )
    journal = PaperPortfolioJournal(portfolio_id, journals)
    store.save(journal)
    return PersistentPaperPortfolio(journal=journal, store=store, resumed=False)


class NautilusStreamingPaperPortfolioExecution:
    def __init__(
        self,
        *,
        candidates: Sequence[StrategyGenome],
        risk_runtime: RiskRuntime,
        journal: PaperPortfolioJournal,
        instruments: Mapping[str, object],
        initial_bars: Mapping[str, Sequence[MarketBar]] | None = None,
        telemetry_provider: Callable[[StrategyGenome], Mapping[str, object] | None] | None = None,
    ) -> None:
        from .nautilus_backtest import _build_binance_spot_engine_for_instruments
        from .nautilus_strategy import compile_genome_to_nautilus

        candidates = tuple(candidates)
        if len(candidates) < 2:
            raise ValueError("paper portfolio requires at least two candidates")
        if len({candidate.strategy_id for candidate in candidates}) != len(candidates):
            raise ValueError("paper portfolio strategy identities must be unique")
        for candidate in candidates:
            if len(candidate.instruments) != 1 or tuple(candidate.data_requirements) != ("BAR",):
                raise RuntimeError("shared PAPER portfolio currently admits single-leg BAR strategies only")
            if candidate.strategy_id not in journal.strategy_ids:
                raise ValueError("paper portfolio journal is missing a candidate")
            instrument_id = candidate.instruments[0]
            if instrument_id not in instruments:
                raise ValueError(f"paper portfolio instrument is unavailable: {instrument_id}")

        unique_instruments = [instruments[key] for key in dict.fromkeys(
            candidate.instruments[0] for candidate in candidates
        )]
        balances: list[str] = []
        seen_currency: set[str] = set()
        for instrument in unique_instruments:
            base = str(instrument.base_currency)
            quote = str(instrument.quote_currency)
            if base not in seen_currency:
                balances.append(f"10 {base}")
                seen_currency.add(base)
            if quote not in seen_currency:
                balances.append(f"100000 {quote}")
                seen_currency.add(quote)

        self._engine = _build_binance_spot_engine_for_instruments(
            instruments=unique_instruments,
            starting_balances=tuple(balances),
        )
        self._instruments = dict(instruments)
        self._journal = journal
        self._risk_runtime = risk_runtime
        self._telemetry_provider = telemetry_provider
        self._strategies: list[object] = []
        self._sinks: dict[str, NautilusPaperEventSink] = {}
        self._last_telemetry: dict[str, dict[str, object]] = {}
        self._bar_types: dict[tuple[str, str], object] = {}
        self._latest_prices: dict[str, float] = {}
        self._initial_equity: float | None = None
        self._peak_equity: float | None = None
        self._risk_summary: dict[str, object] = {
            "portfolio_equity": None,
            "portfolio_daily_pnl": 0.0,
            "portfolio_drawdown": 0.0,
            "portfolio_exposure": 0.0,
            "portfolio_leverage": 0.0,
        }
        initial_bars = {} if initial_bars is None else dict(initial_bars)

        for candidate in candidates:
            instrument = instruments[candidate.instruments[0]]
            compiled = compile_genome_to_nautilus(
                candidate,
                instrument=instrument,
                risk_runtime=risk_runtime,
            )
            sink = NautilusPaperEventSink(journal.journal(candidate.strategy_id))
            self._sinks[candidate.strategy_id] = sink
            strategy_type = type(compiled)

            def recording_type(base_type, event_sink):
                class RecordingStrategy(base_type):
                    def on_position_closed(self, event):
                        event_sink.on_position_closed(event)
                        parent = getattr(super(), "on_position_closed", None)
                        if parent is not None:
                            parent(event)
                return RecordingStrategy

            RecordingStrategy = recording_type(strategy_type, sink)
            try:
                strategy = RecordingStrategy(
                    config=compiled.config,
                    genome=candidate,
                    risk_runtime=risk_runtime,
                    initial_bars=initial_bars.get(candidate.strategy_id, ()),
                )
            except TypeError as exc:
                raise RuntimeError(
                    "paper portfolio strategy does not support deterministic closed-bar bootstrap"
                ) from exc
            self._strategies.append(strategy)
            self._bar_types[(candidate.instruments[0], candidate.timeframe)] = strategy.config.bar_type
            self._engine.add_strategy(strategy)

        self._engine.run(streaming=True)
        self._closed = False

    @property
    def strategies(self) -> tuple[object, ...]:
        return tuple(self._strategies)

    def _instrument_id(self, raw: str, venue: str) -> str:
        qualified = raw if "." in raw else f"{raw}.{venue}"
        if qualified not in self._instruments:
            raise RuntimeError(f"paper portfolio received an unconfigured instrument: {qualified}")
        return qualified

    def _bar(self, event: MarketStreamEvent):
        from nautilus_trader.model.data import Bar
        from nautilus_trader.model.objects import Price, Quantity

        instrument_id = self._instrument_id(event.bar.instrument, event.bar.venue)
        instrument = self._instruments[instrument_id]
        try:
            bar_type = self._bar_types[(instrument_id, event.bar.timeframe)]
        except KeyError as exc:
            raise RuntimeError(
                f"paper portfolio received an unconfigured timeframe: {instrument_id} {event.bar.timeframe}"
            ) from exc
        precision = int(instrument.price_precision)
        size_precision = int(instrument.size_precision)
        return Bar(
            bar_type=bar_type,
            open=Price.from_str(f"{float(event.bar.open):.{precision}f}"),
            high=Price.from_str(f"{float(event.bar.high):.{precision}f}"),
            low=Price.from_str(f"{float(event.bar.low):.{precision}f}"),
            close=Price.from_str(f"{float(event.bar.close):.{precision}f}"),
            volume=Quantity.from_str(f"{float(event.bar.volume):.{size_precision}f}"),
            ts_event=event.timestamp_ns,
            ts_init=event.timestamp_ns,
        )

    def _quote(self, event: MarketStreamEvent):
        from nautilus_trader.model.data import QuoteTick
        from nautilus_trader.model.objects import Price, Quantity

        instrument_id = self._instrument_id(event.tick.instrument, event.tick.venue)
        instrument = self._instruments[instrument_id]
        precision = int(instrument.price_precision)
        size_precision = int(instrument.size_precision)
        return QuoteTick(
            instrument_id=instrument.id,
            bid_price=Price.from_str(f"{float(event.tick.bid):.{precision}f}"),
            ask_price=Price.from_str(f"{float(event.tick.ask):.{precision}f}"),
            bid_size=Quantity.from_str(f"{float(event.tick.bid_size):.{size_precision}f}"),
            ask_size=Quantity.from_str(f"{float(event.tick.ask_size):.{size_precision}f}"),
            ts_event=event.timestamp_ns,
            ts_init=event.timestamp_ns,
        )

    def _update_price(self, event: MarketStreamEvent) -> str:
        instrument_id = self._instrument_id(event.data.instrument, event.data.venue)
        if event.kind == "bar":
            price = float(event.bar.close)
        else:
            price = (float(event.tick.bid) + float(event.tick.ask)) / 2.0
        self._latest_prices[instrument_id] = price
        return instrument_id

    def _refresh_account_risk(self) -> None:
        provider = self._risk_runtime.state_provider
        if not isinstance(provider, RiskStateProvider):
            return
        state = self.execution_state(account_id=f"paper:{self._journal.portfolio_id}")
        exposures: dict[str, float] = {}
        for instrument_id in self._instruments:
            quantity = float(state.positions.get(instrument_id, Decimal("0")))
            price = self._latest_prices.get(instrument_id, 0.0)
            exposures[instrument_id] = abs(quantity * price)
        portfolio_exposure = sum(exposures.values())

        equity = 0.0
        for currency, amount in state.balances.items():
            numeric = float(amount)
            if currency in {"USDT", "USD", "USDC"}:
                equity += numeric
                continue
            matched = next(
                (
                    instrument_id
                    for instrument_id, instrument in self._instruments.items()
                    if str(instrument.base_currency) == currency
                ),
                None,
            )
            if matched is not None:
                equity += numeric * self._latest_prices.get(matched, 0.0)
        complete_prices = all(
            instrument_id in self._latest_prices for instrument_id in self._instruments
        )
        if equity > 0.0 and complete_prices:
            if self._initial_equity is None:
                self._initial_equity = equity
            self._peak_equity = equity if self._peak_equity is None else max(self._peak_equity, equity)
        initial = equity if self._initial_equity is None else self._initial_equity
        peak = equity if self._peak_equity is None else self._peak_equity
        daily_pnl = 0.0 if not complete_prices else equity - initial
        drawdown = 0.0 if not complete_prices or peak <= 0.0 else max(0.0, (peak - equity) / peak)
        leverage = 0.0 if not complete_prices or equity <= 0.0 else portfolio_exposure / equity
        self._risk_summary = {
            "portfolio_equity": equity if complete_prices else None,
            "portfolio_daily_pnl": daily_pnl,
            "portfolio_drawdown": drawdown,
            "portfolio_exposure": portfolio_exposure,
            "portfolio_leverage": leverage,
        }

        for instrument_id in self._instruments:
            provider.update_account_state(
                symbol=instrument_id,
                portfolio_id="default",
                symbol_exposure=exposures[instrument_id],
                portfolio_exposure=portfolio_exposure,
                daily_pnl=daily_pnl,
                drawdown=drawdown,
                leverage=leverage,
                correlated_exposure=portfolio_exposure,
            )

    def _record_telemetry(self, timestamp_ns: int) -> None:
        for strategy in self._strategies:
            strategy_id = strategy.genome.strategy_id
            telemetry = dict(strategy.runtime_telemetry())
            telemetry.update(self._risk_summary)
            if self._telemetry_provider is not None:
                external = self._telemetry_provider(strategy.genome)
                if external is not None:
                    overlap = set(telemetry) & set(external)
                    if overlap:
                        raise RuntimeError(
                            "portfolio telemetry provider overlaps strategy telemetry: "
                            + ", ".join(sorted(overlap))
                        )
                    telemetry.update(external)
            previous = self._last_telemetry.get(strategy_id)
            if telemetry == previous:
                continue
            self._journal.journal(strategy_id).record_strategy_telemetry(
                telemetry,
                timestamp_ns=max(timestamp_ns, self._journal.journal(strategy_id).latest_timestamp_ns),
            )
            self._last_telemetry[strategy_id] = dict(telemetry)

    def dispatch(self, event: MarketStreamEvent) -> None:
        if self._closed:
            raise RuntimeError("Nautilus PAPER portfolio execution is already finalized")
        self._update_price(event)
        self._refresh_account_risk()
        data = self._bar(event) if event.kind == "bar" else self._quote(event)
        self._engine.add_data([data])
        self._engine.run(streaming=True)
        self._record_telemetry(event.timestamp_ns)
        self._refresh_account_risk()
        self._engine.clear_data()

    def execution_state(self, *, account_id: str) -> ExecutionState:
        from nautilus_trader.model.identifiers import Venue

        positions: dict[str, object] = {}
        for position in self._engine.cache.positions_open():
            instrument_id = position.instrument_id.value
            positions[instrument_id] = positions.get(instrument_id, 0) + position.signed_decimal_qty()
        open_order_ids = frozenset(
            order.client_order_id.value for order in self._engine.cache.orders_open()
        )
        account = self._engine.cache.account_for_venue(Venue("BINANCE"))
        if account is None:
            raise RuntimeError("Nautilus PAPER portfolio account state is unavailable")
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
