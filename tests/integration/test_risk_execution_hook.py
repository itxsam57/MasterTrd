from mastertrd.genome import StrategyGenome
from mastertrd.nautilus_backtest import run_binance_spot_strategy_history
from mastertrd.nautilus_risk_hook import NautilusRiskMixin
from mastertrd.nautilus_strategy import compile_genome_to_nautilus
from mastertrd.risk import RiskAction, RiskLimits
from mastertrd.risk_profiles import build_research_backtest_risk_runtime
from mastertrd.risk_runtime import RiskRuntime
from mastertrd.risk_state import RiskStateProvider


def test_compiled_strategy_records_risk_allow_before_every_simulated_order():
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    genome = StrategyGenome(
        strategy_id="risk-hook-ema-1",
        family="trend",
        style="day",
        instruments=(instrument.id.value,),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8},
        exit={"kind": "cross_reverse"},
        allow_short=True,
    )
    strategy = compile_genome_to_nautilus(
        genome,
        instrument=instrument,
        trade_size="0.10000",
        risk_runtime=build_research_backtest_risk_runtime(),
    )
    bar_type = strategy.config.bar_type
    prices = [2100 - i * 2 for i in range(15)] + [2070 + i * 5 for i in range(20)] + [2165 - i * 6 for i in range(20)]
    base_ns = 1_700_000_000_000_000_000
    bars = []
    previous = prices[0] + 1
    for index, close in enumerate(prices):
        open_value = float(previous)
        close_value = float(close)
        bars.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{open_value:.2f}"),
                high=Price.from_str(f"{max(open_value, close_value) + 1.0:.2f}"),
                low=Price.from_str(f"{min(open_value, close_value) - 1.0:.2f}"),
                close=Price.from_str(f"{close_value:.2f}"),
                volume=Quantity.from_str("1.00000"),
                ts_event=base_ns + index * 60_000_000_000,
                ts_init=base_ns + index * 60_000_000_000,
            )
        )
        previous = close

    summary = run_binance_spot_strategy_history(
        instrument=instrument,
        data=bars,
        strategy=strategy,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert summary.order_count >= 1
    assert strategy.risk_runtime.decisions
    assert strategy.risk_runtime.allow_count >= summary.order_count
    assert all(decision.action is RiskAction.ALLOW for decision in strategy.risk_runtime.accepted_decisions)
    assert strategy.risk_runtime.accepted_order_fingerprints


def test_nautilus_risk_hook_blocks_from_nonzero_owned_account_state() -> None:
    provider = RiskStateProvider(clock=lambda: 1_000.0, max_market_age_seconds=5.0)
    provider.update_account_state(
        symbol="ETHUSDT.BINANCE",
        portfolio_id="default",
        symbol_exposure=19_900.0,
        portfolio_exposure=19_900.0,
        daily_pnl=0.0,
        drawdown=0.0,
        leverage=1.0,
        correlated_exposure=0.0,
    )
    provider.update_market_state(
        symbol="ETHUSDT.BINANCE",
        spread_bps=5.0,
        realized_volatility=0.05,
        observed_at=999.0,
    )
    provider.update_reconciliation(ok=True, observed_at=999.0)
    provider.update_venue_state(
        venue="BINANCE",
        healthy=True,
        api_error_rate=0.0,
        api_latency_ms=20.0,
    )
    runtime = RiskRuntime(
        RiskLimits(
            max_order_notional=10_000.0,
            max_symbol_exposure=20_000.0,
            max_portfolio_exposure=50_000.0,
            max_daily_loss=2_000.0,
            max_drawdown=0.25,
            max_orders_per_minute=30,
            max_leverage=4.0,
            max_correlated_exposure=25_000.0,
            max_spread_bps=30.0,
            max_realized_volatility=0.10,
            max_api_error_rate=0.10,
            max_api_latency_ms=1_500.0,
            max_reconciliation_age_seconds=60.0,
        ),
        state_provider=provider,
    )

    class VenueId:
        value = "BINANCE"

    class InstrumentId:
        value = "ETHUSDT.BINANCE"
        venue = VenueId()

    class Order:
        instrument_id = InstrumentId()
        quantity = 0.10
        side = "BUY"
        order_type = "MARKET"

    class OrderSink:
        def __init__(self) -> None:
            self.submitted = []

        def submit_order(self, order, *args, **kwargs):
            self.submitted.append(order)
            return "submitted"

    class RiskHarness(NautilusRiskMixin, OrderSink):
        def __init__(self) -> None:
            OrderSink.__init__(self)
            self._configure_risk_runtime("risk-hook-owned-state", runtime)

        def _risk_reference_price(self, instrument_id) -> float:
            return 2_100.0

    harness = RiskHarness()
    result = harness.submit_order(Order())

    assert result is None
    assert harness.submitted == []
    assert runtime.decisions[-1].action is RiskAction.BLOCK_ORDER
    assert "order risk" in runtime.decisions[-1].reason


def test_risk_telemetry_retains_last_rejection_after_later_allow() -> None:
    provider = RiskStateProvider(clock=lambda: 1_000.0, max_market_age_seconds=5.0)
    provider.update_account_state(
        symbol="ETHUSDT.BINANCE", portfolio_id="default",
        symbol_exposure=19_900.0, portfolio_exposure=19_900.0,
        daily_pnl=0.0, drawdown=0.0, leverage=1.0, correlated_exposure=0.0,
    )
    provider.update_market_state(
        symbol="ETHUSDT.BINANCE", spread_bps=5.0,
        realized_volatility=0.05, observed_at=999.0,
    )
    provider.update_reconciliation(ok=True, observed_at=999.0)
    provider.update_venue_state(
        venue="BINANCE", healthy=True, api_error_rate=0.0, api_latency_ms=20.0,
    )
    runtime = RiskRuntime(RiskLimits(10_000, 20_000, 50_000, 2_000, 0.25, 30), state_provider=provider)

    class VenueId:
        value = "BINANCE"
    class InstrumentId:
        value = "ETHUSDT.BINANCE"
        venue = VenueId()
    class Order:
        instrument_id = InstrumentId()
        quantity = 0.10
        side = "BUY"
        order_type = "MARKET"
    class Sink:
        def __init__(self) -> None:
            self.submitted = 0
        def submit_order(self, order, *args, **kwargs):
            self.submitted += 1
            return "submitted"
    class Harness(NautilusRiskMixin, Sink):
        def __init__(self) -> None:
            Sink.__init__(self)
            self._configure_risk_runtime("retain-rejection", runtime)
        def _risk_reference_price(self, instrument_id) -> float:
            return 2_100.0

    harness = Harness()
    assert harness.submit_order(Order()) is None
    rejected = harness.risk_telemetry()["last_risk_rejection"]
    assert rejected is not None
    provider.update_account_state(
        symbol="ETHUSDT.BINANCE", portfolio_id="default",
        symbol_exposure=0.0, portfolio_exposure=0.0,
        daily_pnl=0.0, drawdown=0.0, leverage=1.0, correlated_exposure=0.0,
    )

    assert harness.submit_order(Order()) == "submitted"
    telemetry = harness.risk_telemetry()
    assert telemetry["orders_rejected"] == 1
    assert telemetry["orders_allowed"] == 1
    assert telemetry["last_risk_rejection"] == rejected
