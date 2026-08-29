from mastertrd.execution import BinanceExecutionProfile
from mastertrd.nautilus_live import build_nautilus_binance_trading_node
from mastertrd.venue import BinanceProduct


def test_locked_nautilus_binance_trading_node_builds_without_connecting():
    from nautilus_trader.live.node import TradingNode

    profile = BinanceExecutionProfile(
        product=BinanceProduct.SPOT,
        environment="TESTNET",
        api_key="offline-test-key",
        api_secret="offline-test-secret",
    )
    node = build_nautilus_binance_trading_node(
        profile=profile,
        account_id="OFFLINE-TESTNET-ACCOUNT",
        trader_id="MASTERTRD-TEST-001",
    )
    try:
        assert isinstance(node, TradingNode)
        assert not node.is_running
    finally:
        node.dispose()
