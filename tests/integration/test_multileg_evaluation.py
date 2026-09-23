from __future__ import annotations

from mastertrd.genome import StrategyGenome
from mastertrd import nautilus_evaluation


def _bars(instrument, closes: list[float]):
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price

    bar_type = BarType.from_str(f"{instrument.id.value}-1-MINUTE-LAST-EXTERNAL")
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
                volume=instrument.make_qty(10),
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
            eth.id.value: _bars(eth, [100, 100, 100, 120, 100, 100, 100, 100]),
            btc.id.value: _bars(btc, [100, 100, 100, 100, 100, 100, 100, 100]),
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
            data_by_instrument={eth.id.value: _bars(eth, [100, 100, 100, 120])},
            dataset_hash="multileg-dataset-missing",
            code_hash="multileg-code-v1",
            trade_size_override="0.10",
            starting_balances=("10 ETH", "10 BTC", "100000 USDT"),
        )


def test_usdm_stat_arb_real_execution_stress_is_derived_from_nautilus_fills() -> None:
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from mastertrd.multi_leg_validation import (
        MultiLegStressPolicy,
        multi_leg_execution_stress_evidence,
        run_nautilus_multi_leg_stress,
    )
    from mastertrd.strategy_universe import compile_strategy_recipe

    btc = TestInstrumentProvider.btcusdt_perp_binance()
    eth = TestInstrumentProvider.ethusdt_perp_binance()
    candidate = compile_strategy_recipe(
        "pairs-cointegration-balanced",
        instruments=(btc.id.value, eth.id.value),
        seed=42,
        trade_size="0.01000",
        timeframe="15m",
    )

    def make_bars(instrument, closes):
        bar_type = BarType.from_str(
            f"{instrument.id.value}-15-MINUTE-LAST-EXTERNAL"
        )
        base_ns = 1_700_000_000_000_000_000
        output = []
        previous = closes[0]
        for index, close in enumerate(closes):
            open_value = float(previous)
            close_value = float(close)
            timestamp = base_ns + index * 900_000_000_000
            output.append(
                Bar(
                    bar_type=bar_type,
                    open=instrument.make_price(open_value),
                    high=instrument.make_price(max(open_value, close_value) + 1.0),
                    low=instrument.make_price(min(open_value, close_value) - 1.0),
                    close=instrument.make_price(close_value),
                    volume=instrument.make_qty(10),
                    ts_event=timestamp,
                    ts_init=timestamp,
                )
            )
            previous = close
        return tuple(output)

    count = 800
    btc_closes = [100.0 + (index % 20) * 0.1 for index in range(count)]
    eth_closes = []
    for index in range(count):
        offset = {0: 0.0, 1: 20.0, 2: 0.0, 3: -20.0}[(index // 80) % 4]
        eth_closes.append(100.0 + (index % 20) * 0.1 + offset)

    report = run_nautilus_multi_leg_stress(
        candidate,
        instruments={btc.id.value: btc, eth.id.value: eth},
        data_by_instrument={
            btc.id.value: make_bars(btc, btc_closes),
            eth.id.value: make_bars(eth, eth_closes),
        },
        dataset_hash="usdm-multileg-stress-v1",
        code_hash="code-usdm-multileg",
        trade_size="0.01000",
        starting_balances=("100000 USDT",),
    )

    assert report.engine == "nautilus_trader"
    assert report.expected_legs == 2
    assert report.completed_cycles >= 1
    assert report.leg_fill_counts[0] == report.leg_fill_counts[1]
    assert report.residual_exposure_ratio == 0.0
    assert report.slippage_bps == 0.0

    evidence = multi_leg_execution_stress_evidence(
        candidate,
        report,
        MultiLegStressPolicy(
            min_completed_cycles=1,
            max_leg_fill_skew=0.0,
            max_residual_exposure_ratio=0.0,
            max_slippage_bps=5.0,
        ),
    )
    assert evidence.passed is True
