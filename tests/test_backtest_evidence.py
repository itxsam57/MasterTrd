from mastertrd.contracts import EvaluationResult, StrategyState
from mastertrd.genome import StrategyGenome
from mastertrd.governor import evaluate_validated_promotion
from mastertrd.validation import nautilus_backtest_evidence


def _genome() -> StrategyGenome:
    return StrategyGenome(
        strategy_id="S-trend-evidence",
        family="trend",
        style="day",
        instruments=("BTCUSDT.BINANCE",),
        timeframe="1m",
        entry={"kind": "ema_cross", "fast_period": 3, "slow_period": 8, "trade_size": "0.10"},
        exit={"kind": "cross_reverse"},
    )


def _result(genome: StrategyGenome, *, trade_count: int) -> EvaluationResult:
    return EvaluationResult(
        strategy_id=genome.strategy_id,
        genome_hash=genome.genome_hash,
        dataset_hash="d" * 64,
        code_hash="c" * 64,
        engine="nautilus_trader",
        engine_version="1.231.0",
        total_return=0.01,
        sharpe=0.5,
        sortino=0.7,
        max_drawdown=0.02,
        profit_factor=1.2,
        expectancy=0.003,
        trade_count=trade_count,
        turnover=0.1,
        fees=0.001,
        slippage=0.001,
        scores={"execution_backtest": 1.0 if trade_count else 0.0},
    )


def test_real_backtest_result_becomes_hashed_promotion_evidence():
    genome = _genome()
    record = nautilus_backtest_evidence(_result(genome, trade_count=3))

    assert record.evidence_type == "nautilus_backtest"
    assert record.strategy_id == genome.strategy_id
    assert record.genome_hash == genome.genome_hash
    assert record.passed is True
    assert len(record.evidence_hash) == 64

    decision = evaluate_validated_promotion(
        StrategyState.SCREENED,
        StrategyState.BACKTESTED,
        genome,
        [record],
    )
    assert decision.allowed is True


def test_zero_trade_backtest_cannot_promote():
    genome = _genome()
    record = nautilus_backtest_evidence(_result(genome, trade_count=0))

    assert record.passed is False
    decision = evaluate_validated_promotion(
        StrategyState.SCREENED,
        StrategyState.BACKTESTED,
        genome,
        [record],
    )
    assert decision.allowed is False
    assert decision.missing_evidence == frozenset({"nautilus_backtest"})
