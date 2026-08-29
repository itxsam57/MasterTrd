import pytest

from mastertrd.contracts import RuntimeMode
from mastertrd.live_node import build_exchange_node, run_exchange_service
from mastertrd.runtime import RuntimeConfig
from mastertrd.venue import BinanceProduct


class FakeNode:
    def __init__(self, *, fail_on_run: bool = False):
        self.events: list[str] = []
        self.fail_on_run = fail_on_run

    def run(self) -> None:
        self.events.append("run")
        if self.fail_on_run:
            raise RuntimeError("node failed")

    def dispose(self) -> None:
        self.events.append("dispose")


def test_paper_mode_cannot_construct_exchange_execution_node():
    runtime = RuntimeConfig(mode=RuntimeMode.PAPER, live_trading_enabled=False, oracle_enabled=False)
    calls: list[object] = []

    def builder(**kwargs):
        calls.append(kwargs)
        return FakeNode()

    with pytest.raises(RuntimeError, match="PAPER"):
        build_exchange_node(
            runtime,
            {},
            product=BinanceProduct.SPOT,
            node_builder=builder,
        )

    assert calls == []


def test_testnet_node_uses_only_testnet_credentials_and_requested_product():
    runtime = RuntimeConfig(mode=RuntimeMode.TESTNET, live_trading_enabled=False, oracle_enabled=False)
    captured: dict[str, object] = {}

    def builder(**kwargs):
        captured.update(kwargs)
        return FakeNode()

    node = build_exchange_node(
        runtime,
        {
            "BINANCE_TESTNET_API_KEY": "test-key",
            "BINANCE_TESTNET_API_SECRET": "test-secret",
            "BINANCE_TESTNET_ACCOUNT_ID": "TESTNET-ACCOUNT",
            "BINANCE_LIVE_API_KEY": "must-not-be-used",
            "BINANCE_LIVE_API_SECRET": "must-not-be-used",
            "BINANCE_LIVE_ACCOUNT_ID": "must-not-be-used",
        },
        product=BinanceProduct.USD_M,
        node_builder=builder,
    )

    assert isinstance(node, FakeNode)
    assert captured["account_id"] == "TESTNET-ACCOUNT"
    profile = captured["profile"]
    assert profile.environment == "TESTNET"
    assert profile.product is BinanceProduct.USD_M
    assert profile.api_key == "test-key"
    assert profile.api_secret == "test-secret"


def test_live_node_requires_live_runtime_gate_even_if_dataclass_is_constructed_directly():
    runtime = RuntimeConfig(mode=RuntimeMode.LIVE, live_trading_enabled=False, oracle_enabled=False)

    with pytest.raises(RuntimeError, match="LIVE"):
        build_exchange_node(
            runtime,
            {
                "BINANCE_LIVE_API_KEY": "live-key",
                "BINANCE_LIVE_API_SECRET": "live-secret",
                "BINANCE_LIVE_ACCOUNT_ID": "LIVE-ACCOUNT",
            },
            product=BinanceProduct.SPOT,
            node_builder=lambda **_: FakeNode(),
        )


def test_exchange_service_always_disposes_node_after_normal_stop():
    node = FakeNode()
    runtime = RuntimeConfig(mode=RuntimeMode.DEMO, live_trading_enabled=False, oracle_enabled=False)

    readiness = run_exchange_service(
        runtime,
        {
            "BINANCE_DEMO_API_KEY": "demo-key",
            "BINANCE_DEMO_API_SECRET": "demo-secret",
            "BINANCE_DEMO_ACCOUNT_ID": "DEMO-ACCOUNT",
        },
        product=BinanceProduct.SPOT,
        node_builder=lambda **_: node,
    )

    assert readiness.value == "EXCHANGE_READY"
    assert node.events == ["run", "dispose"]


def test_exchange_service_disposes_node_when_nautilus_run_fails():
    node = FakeNode(fail_on_run=True)
    runtime = RuntimeConfig(mode=RuntimeMode.TESTNET, live_trading_enabled=False, oracle_enabled=False)

    with pytest.raises(RuntimeError, match="node failed"):
        run_exchange_service(
            runtime,
            {
                "BINANCE_TESTNET_API_KEY": "test-key",
                "BINANCE_TESTNET_API_SECRET": "test-secret",
                "BINANCE_TESTNET_ACCOUNT_ID": "TESTNET-ACCOUNT",
            },
            product=BinanceProduct.SPOT,
            node_builder=lambda **_: node,
        )

    assert node.events == ["run", "dispose"]
