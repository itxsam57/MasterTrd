from __future__ import annotations

import asyncio
import hashlib
from importlib.metadata import version

from .genome import StrategyGenome
from .paper_evidence import PaperStartReceipt


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
