from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
from pathlib import Path

from .genome import StrategyGenome
from .paper_evidence import PaperStartReceipt
from .paper_session import JsonPaperSessionStore, PaperSessionJournal


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
