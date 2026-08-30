from dataclasses import replace
from datetime import datetime, timedelta, timezone

from mastertrd.advanced_validation import AdvancedValidationPolicy
from mastertrd.asset_transfer import AssetTransferPolicy
from mastertrd.contracts import MarketBar, StrategyState
from mastertrd.nautilus_data import market_bars_to_nautilus
from mastertrd.research.generator import generate_candidate
from mastertrd.robustness import RobustnessPolicy
from mastertrd.robustness_cycle import run_generated_robustness_cycle


def _step(timeframe: str) -> timedelta:
    value = int(timeframe[:-1])
    return timedelta(minutes=value) if timeframe.endswith("m") else timedelta(hours=value)


def _bars(candidate, instrument, *, start, offset=0.0):
    closes = (
        [2300.0 + offset - i * 2.0 for i in range(100)]
        + [2100.0 + offset + i * 4.0 for i in range(100)]
        + [2496.0 + offset - i * 5.0 for i in range(100)]
    )
    step = _step(candidate.timeframe)
    market = []
    previous = closes[0] + 1.0
    for index, close in enumerate(closes):
        market.append(
            MarketBar(
                venue=str(instrument.id.venue),
                instrument=str(instrument.raw_symbol),
                timeframe=candidate.timeframe,
                timestamp=start + step * index,
                open=previous,
                high=max(previous, close) + 1.0,
                low=min(previous, close) - 1.0,
                close=close,
                volume=1.0,
            )
        )
        previous = close
    return market_bars_to_nautilus(market, instrument=instrument)


def test_generated_candidate_runs_real_robustness_suite_and_can_reach_robust():
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    instrument = TestInstrumentProvider.ethusdt_binance()
    transfer_instrument = TestInstrumentProvider.btcusdt_binance()
    candidate = generate_candidate(family="trend", instruments=(instrument.id.value,), seed=42)
    transfer_candidate = replace(candidate, instruments=(transfer_instrument.id.value,))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base = _bars(candidate, instrument, start=start)
    fold_span = _step(candidate.timeframe) * 400
    folds = [
        ("fold-a", _bars(candidate, instrument, start=start + fold_span, offset=0.0)),
        ("fold-b", _bars(candidate, instrument, start=start + fold_span * 2, offset=25.0)),
        ("fold-c", _bars(candidate, instrument, start=start + fold_span * 3, offset=-25.0)),
    ]
    cpcv = [
        (f"cpcv-{index}", _bars(candidate, instrument, start=start + fold_span * (4 + index), offset=offset))
        for index, offset in enumerate((10.0, -10.0, 20.0, -20.0))
    ]
    monte_carlo = [
        (f"mc-{index}", _bars(candidate, instrument, start=start + fold_span * (8 + index), offset=offset))
        for index, offset in enumerate((5.0, -5.0, 15.0, -15.0, 30.0))
    ]
    transfer = [
        (
            "transfer-btc-v1",
            transfer_candidate,
            transfer_instrument,
            _bars(
                transfer_candidate,
                transfer_instrument,
                start=start + fold_span * 14,
                offset=0.0,
            ),
        )
    ]
    policy = RobustnessPolicy(
        min_trades_per_slice=1,
        min_profitable_slice_ratio=0.67,
        max_drawdown=0.50,
        min_stressed_return=-0.20,
        max_return_degradation=1.0,
        min_stable_neighbor_ratio=0.50,
    )
    advanced_policy = AdvancedValidationPolicy(
        min_evaluations=4,
        min_trades_per_evaluation=1,
        min_positive_ratio=0.50,
        max_drawdown=0.90,
        min_monte_carlo_survival_ratio=0.80,
        max_monte_carlo_loss=-1.0,
    )
    transfer_policy = AssetTransferPolicy(
        min_transfer_assets=1,
        min_trades_per_asset=1,
        min_pass_ratio=1.0,
        min_total_return=-1.0,
        max_drawdown=0.90,
    )

    cycle = run_generated_robustness_cycle(
        candidate=candidate,
        instrument=instrument,
        data=base,
        dataset_hash="robustness-base-v1",
        fold_datasets=folds,
        cpcv_datasets=cpcv,
        monte_carlo_datasets=monte_carlo,
        transfer_datasets=transfer,
        code_hash="robustness-code-v1",
        trade_size="0.01000",
        policy=policy,
        advanced_policy=advanced_policy,
        transfer_policy=transfer_policy,
        stressed_fees=0.001,
        stressed_slippage=0.001,
        starting_balances=("10 ETH", "100000 USDT"),
    )

    assert cycle.base_result.trade_count >= 1
    assert cycle.stressed_result.total_return < cycle.base_result.total_return
    assert len(cycle.fold_results) == 3
    assert len(cycle.neighbor_results) >= 2
    assert len(cycle.cpcv_results) == 4
    assert len(cycle.monte_carlo_results) == 5
    assert len(cycle.transfer_results) == 1
    assert cycle.transfer_results[0].trade_count >= 1
    assert {record.evidence_type for record in cycle.evidence} == {
        "walk_forward",
        "cost_stress",
        "parameter_stability",
        "purged_cpcv",
        "monte_carlo",
        "asset_transfer",
    }
    assert all(record.passed for record in cycle.evidence)
    assert cycle.promotion.allowed is True
    assert cycle.promotion.target is StrategyState.ROBUST
