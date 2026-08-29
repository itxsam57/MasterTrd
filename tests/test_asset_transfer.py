from dataclasses import replace

import pytest

from mastertrd.asset_transfer import AssetTransferPolicy, asset_transfer_evidence
from mastertrd.contracts import EvaluationResult
from mastertrd.genome import StrategyGenome


def genome(instrument: str = "ETHUSDT.BINANCE") -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-transfer-trend",
        family="trend",
        style="day",
        instruments=(instrument,),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 5, "slow_period": 20, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
        filters={"min_volume": 1.0},
        risk={"risk_fraction": 0.01},
    )


def result(candidate: StrategyGenome, *, dataset_hash: str, total_return: float = 0.04) -> EvaluationResult:
    return EvaluationResult(
        strategy_id=candidate.strategy_id,
        genome_hash=candidate.genome_hash,
        dataset_hash=dataset_hash,
        code_hash="c" * 64,
        engine="nautilus_trader",
        engine_version="1.231.0",
        total_return=total_return,
        sharpe=0.8,
        sortino=1.0,
        max_drawdown=0.10,
        profit_factor=1.2,
        expectancy=0.003,
        trade_count=10,
        turnover=0.4,
        fees=0.002,
        slippage=0.002,
        scores={"execution_backtest": 1.0},
    )


def policy() -> AssetTransferPolicy:
    return AssetTransferPolicy(
        min_transfer_assets=2,
        min_trades_per_asset=5,
        min_pass_ratio=0.50,
        min_total_return=0.0,
        max_drawdown=0.25,
    )


def test_same_strategy_logic_on_distinct_assets_produces_transfer_evidence():
    candidate = genome()
    btc = genome("BTCUSDT.BINANCE")
    sol = genome("SOLUSDT.BINANCE")

    evidence = asset_transfer_evidence(
        candidate,
        [
            (btc, result(btc, dataset_hash="1" * 64)),
            (sol, result(sol, dataset_hash="2" * 64, total_return=-0.01)),
        ],
        policy(),
    )

    assert evidence.evidence_type == "asset_transfer"
    assert evidence.strategy_id == candidate.strategy_id
    assert evidence.genome_hash == candidate.genome_hash
    assert evidence.passed is True
    assert evidence.metrics["transfer_asset_count"] == 2.0
    assert evidence.metrics["passing_asset_ratio"] == 0.5


def test_transfer_rejects_changed_strategy_logic_or_original_instrument():
    candidate = genome()
    btc = genome("BTCUSDT.BINANCE")
    changed_entry = replace(btc, entry={"kind": "ema_cross", "fast_period": 7, "slow_period": 20, "trade_size": "0.10"})

    with pytest.raises(ValueError, match="strategy logic"):
        asset_transfer_evidence(candidate, [(changed_entry, result(changed_entry, dataset_hash="1" * 64))], replace(policy(), min_transfer_assets=1))

    with pytest.raises(ValueError, match="different instruments"):
        asset_transfer_evidence(candidate, [(candidate, result(candidate, dataset_hash="1" * 64))], replace(policy(), min_transfer_assets=1))


def test_transfer_rejects_result_identity_mismatch_and_duplicate_assets():
    candidate = genome()
    btc = genome("BTCUSDT.BINANCE")
    good = result(btc, dataset_hash="1" * 64)

    with pytest.raises(ValueError, match="genome_hash"):
        asset_transfer_evidence(candidate, [(btc, replace(good, genome_hash="x" * 64))], replace(policy(), min_transfer_assets=1))

    with pytest.raises(ValueError, match="unique"):
        asset_transfer_evidence(candidate, [(btc, good), (btc, replace(good, dataset_hash="2" * 64))], policy())


def test_weak_cross_asset_performance_fails_evidence():
    candidate = genome()
    btc = genome("BTCUSDT.BINANCE")
    sol = genome("SOLUSDT.BINANCE")
    weak = asset_transfer_evidence(
        candidate,
        [
            (btc, result(btc, dataset_hash="1" * 64, total_return=-0.05)),
            (sol, result(sol, dataset_hash="2" * 64, total_return=-0.04)),
        ],
        policy(),
    )
    assert weak.passed is False
