from __future__ import annotations

from mastertrd.genome import StrategyGenome
from mastertrd import nautilus_evaluation


def _bars(instrument_id: str, closes: list[float]):
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    bar_type = BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")
    base_ns = 1_700_000_000_000_000_000
    output = []
    previous = closes[0]
    for index, close in enumerate(closes):
        open_value = float(previous)
        close_value = float(close)
        output.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{open_value:.2f}"),
                high=Price.from_str(f"{max(open_value, close_value) + 1.0:.2f}"),
                low=Price.from_str(f"{min(open_value, close_value) - 1.0:.2f}"),
                close=Price.from_str(f"{close_value:.2f}"),
                volume=Quantity.from_str("10.00000"),
                ts_event=base_ns + index * 60_000_000_000,
                ts_init=base_ns + index * 60_000_000_000,
            )
        )
        previous = close
    return tuple(output)


def test_run_nautilus_evaluation_executes_true_multileg_candidate_in_one_engine() -> None:
    assert hasattr(nautilus_evaluation, "run_nautilus_evaluation"), (
        "generalized run_nautilus_evaluation boundary is missing"
    )

    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    eth = TestInstrumentProvider.ethusdt_binance()
    btc = TestInstrumentProvider.btcusdt_binance()
    genome = StrategyGenome(
        strategy_id="multileg-eval-1",
        family="stat_arb",
        style="market_neutral",
        instruments=(eth.id.value, btc.id.value),
        timeframe="1m",
        entry={"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        exit={"type": "spread_mean_exit", "z_exit": 0.5},
        allow_short=True,
    )

    result = nautilus_evaluation.run_nautilus_evaluation(
        genome=genome,
        instruments={eth.id.value: eth, btc.id.value: btc},
        data_by_instrument={
            eth.id.value: _bars(eth.id.value, [100, 100, 100, 120, 100, 100, 100, 100]),
            btc.id.value: _bars(btc.id.value, [100, 100, 100, 100, 100, 100, 100, 100]),
        },
        dataset_hash="multileg-dataset-v1",
        code_hash="multileg-code-v1",
        trade_size_override="0.10",
        starting_balances=("10 ETH", "10 BTC", "100000 USDT"),
    )

    assert result.engine == "nautilus_trader"
    assert result.strategy_id == genome.strategy_id
    assert result.genome_hash == genome.genome_hash
    assert result.dataset_hash == "multileg-dataset-v1"
    assert result.code_hash == "multileg-code-v1"
    assert result.trade_count >= 2


def test_run_nautilus_evaluation_rejects_missing_multileg_data() -> None:
    if not hasattr(nautilus_evaluation, "run_nautilus_evaluation"):
        return

    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    eth = TestInstrumentProvider.ethusdt_binance()
    btc = TestInstrumentProvider.btcusdt_binance()
    genome = StrategyGenome(
        strategy_id="multileg-eval-missing-data",
        family="stat_arb",
        style="market_neutral",
        instruments=(eth.id.value, btc.id.value),
        timeframe="1m",
        entry={"type": "cointegration_spread", "window": 3, "z_entry": 1.0},
        exit={"type": "spread_mean_exit", "z_exit": 0.5},
        allow_short=True,
    )

    import pytest

    with pytest.raises(ValueError, match="missing.*data.*BTCUSDT"):
        nautilus_evaluation.run_nautilus_evaluation(
            genome=genome,
            instruments={eth.id.value: eth, btc.id.value: btc},
            data_by_instrument={eth.id.value: _bars(eth.id.value, [100, 100, 100, 120])},
            dataset_hash="multileg-dataset-missing",
            code_hash="multileg-code-v1",
            trade_size_override="0.10",
            starting_balances=("10 ETH", "10 BTC", "100000 USDT"),
        )
