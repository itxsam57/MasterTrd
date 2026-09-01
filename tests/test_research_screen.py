from datetime import datetime, timedelta, timezone

from mastertrd.contracts import MarketBar
from mastertrd.execution_policy import PositionState, evaluate_execution_policy
from mastertrd.execution_signals import SignalDirection
from mastertrd.genome import StrategyGenome
from mastertrd.research.generator import generate_candidate
from mastertrd.research.screen import _single_leg_signals, screen_genome


def _bars(instrument: str, count: int = 180) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars: list[MarketBar] = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.35 + (2.0 if index % 11 == 0 else 0.0)
        bars.append(
            MarketBar(
                venue="BINANCE",
                instrument=instrument,
                timeframe="15m",
                timestamp=start + timedelta(minutes=15 * index),
                open=previous,
                high=max(previous, close) + 0.5,
                low=min(previous, close) - 0.5,
                close=close,
                volume=1000.0 + index,
            )
        )
        previous = close
    return bars


def _bars_from_closes(instrument: str, closes: list[float]) -> list[MarketBar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    previous = closes[0]
    for index, close in enumerate(closes):
        bars.append(
            MarketBar(
                venue="BINANCE",
                instrument=instrument,
                timeframe="1m",
                timestamp=start + timedelta(minutes=index),
                open=previous,
                high=max(previous, close) + 0.5,
                low=min(previous, close) - 0.5,
                close=close,
                volume=1000.0 + index,
            )
        )
        previous = close
    return bars


class _CountingBar:
    """Count real price-field reads without using a wall-clock benchmark."""

    def __init__(self, bar: MarketBar, counter: list[int]) -> None:
        self._bar = bar
        self._counter = counter

    def _read(self, name: str) -> float:
        self._counter[0] += 1
        return float(getattr(self._bar, name))

    @property
    def close(self) -> float:
        return self._read("close")

    @property
    def high(self) -> float:
        return self._read("high")

    @property
    def low(self) -> float:
        return self._read("low")


def _single_leg_price_reads(genome: StrategyGenome, bars: list[MarketBar]) -> int:
    counter = [0]
    counted = tuple(_CountingBar(bar, counter) for bar in bars)
    _single_leg_signals(genome, counted)
    return counter[0]


def _assert_near_linear_price_reads(genome: StrategyGenome, closes: list[float]) -> None:
    midpoint = len(closes) // 2
    small = _bars_from_closes(genome.instruments[0], closes[:midpoint])
    large = _bars_from_closes(genome.instruments[0], closes)
    small_reads = _single_leg_price_reads(genome, small)
    large_reads = _single_leg_price_reads(genome, large)

    # Doubling a history may do a little more fixed-window work, but must not
    # approach the ~4x field-read growth of the old full-prefix hot loop.
    assert large_reads <= small_reads * 2.5


def _reference_single_leg_signals(
    genome: StrategyGenome,
    bars: list[MarketBar],
) -> tuple[list[bool], list[bool], list[bool], list[bool]]:
    count = len(bars)
    entries = [False] * count
    exits = [False] * count
    short_entries = [False] * count
    short_exits = [False] * count
    position = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)

    for index in range(count):
        current = bars[index]
        if position.direction is not SignalDirection.FLAT:
            position = PositionState(
                direction=position.direction,
                entry_price=position.entry_price,
                peak_price=max(position.peak_price, float(current.high)),
                trough_price=min(position.trough_price, float(current.low)),
                bars_held=position.bars_held + 1,
            )
        decision = evaluate_execution_policy(genome, bars[: index + 1], position)

        if position.direction is SignalDirection.FLAT:
            if decision.direction is SignalDirection.LONG:
                entries[index] = True
                price = float(current.close)
                position = PositionState(SignalDirection.LONG, price, price, price, 0)
            elif decision.direction is SignalDirection.SHORT and genome.allow_short:
                short_entries[index] = True
                price = float(current.close)
                position = PositionState(SignalDirection.SHORT, price, price, price, 0)
            continue

        if not decision.close_position:
            continue
        if position.direction is SignalDirection.LONG:
            exits[index] = True
        else:
            short_exits[index] = True

        if decision.direction is SignalDirection.LONG:
            entries[index] = True
            price = float(current.close)
            position = PositionState(SignalDirection.LONG, price, price, price, 0)
        elif decision.direction is SignalDirection.SHORT and genome.allow_short:
            short_entries[index] = True
            price = float(current.close)
            position = PositionState(SignalDirection.SHORT, price, price, price, 0)
        else:
            position = PositionState(SignalDirection.FLAT, 0.0, 0.0, 0.0, 0)

    return entries, exits, short_entries, short_exits


def _assert_shared_policy_parity(genome: StrategyGenome, bars: list[MarketBar]) -> None:
    actual = _single_leg_signals(genome, bars)
    expected = _reference_single_leg_signals(genome, bars)
    for actual_signal, expected_signal in zip(actual, expected, strict=True):
        assert actual_signal.tolist() == expected_signal


def test_rsi_screen_history_work_scales_near_linearly():
    instrument = "ETHUSDT"
    genome = StrategyGenome(
        strategy_id="screen-rsi-complexity",
        family="momentum",
        style="intraday",
        instruments=(instrument,),
        timeframe="5m",
        entry={"type": "rsi_momentum", "period": 14, "threshold": 101},
        exit={"type": "atr_bracket", "stop_atr": 2.0, "target_atr": 3.0},
        allow_short=False,
    )
    closes = [100.0 + (index % 9) * 0.1 for index in range(480)]

    _assert_near_linear_price_reads(genome, closes)


def test_donchian_screen_history_work_scales_near_linearly():
    instrument = "ETHUSDT"
    genome = StrategyGenome(
        strategy_id="screen-donchian-complexity",
        family="breakout",
        style="intraday",
        instruments=(instrument,),
        timeframe="5m",
        entry={"type": "donchian_breakout", "window": 55},
        exit={"type": "atr_bracket", "stop_atr": 2.0, "target_atr": 3.0},
        allow_short=False,
    )
    closes = [100.0 + (0.05 if index % 2 else 0.0) for index in range(480)]

    _assert_near_linear_price_reads(genome, closes)


def test_rsi_linear_screen_path_matches_shared_execution_policy():
    instrument = "ETHUSDT"
    genome = StrategyGenome(
        strategy_id="screen-rsi-parity",
        family="momentum",
        style="intraday",
        instruments=(instrument,),
        timeframe="5m",
        entry={"type": "rsi_momentum", "period": 14, "threshold": 60},
        exit={"type": "atr_bracket", "stop_atr": 1.8, "target_atr": 2.7, "atr_period": 14},
        allow_short=True,
    )
    closes = [100.0 + index * 0.08 + (2.5 if index % 19 == 0 else -1.5 if index % 13 == 0 else 0.0) for index in range(260)]

    _assert_shared_policy_parity(genome, _bars_from_closes(instrument, closes))


def test_donchian_linear_screen_path_matches_shared_execution_policy():
    instrument = "ETHUSDT"
    genome = StrategyGenome(
        strategy_id="screen-donchian-parity",
        family="breakout",
        style="intraday",
        instruments=(instrument,),
        timeframe="5m",
        entry={"type": "donchian_breakout", "window": 55},
        exit={"type": "atr_bracket", "stop_atr": 2.1, "target_atr": 3.4, "atr_period": 14},
        allow_short=True,
    )
    closes = [100.0 + index * 0.12 + (4.0 if index % 37 == 0 else -3.0 if index % 29 == 0 else 0.0) for index in range(300)]

    _assert_shared_policy_parity(genome, _bars_from_closes(instrument, closes))


def test_screen_result_keeps_original_genome_hash_and_uses_shared_signals():
    genome = generate_candidate(family="momentum", instruments=("ETHUSDT",), seed=42)
    bars = _bars("ETHUSDT")

    result = screen_genome(
        genome,
        {genome.instruments[0]: bars},
        fees=0.001,
        slippage=0.0005,
    )

    assert result.genome_hash == genome.genome_hash
    assert result.engine == "vectorbt"
    assert result.dataset_hash
    assert result.code_hash
    assert result.trade_count >= 0
    assert result.fees == 0.001
    assert result.slippage == 0.0005


def test_screen_executes_atr_exit_and_can_reenter_persistent_signal():
    instrument = "ETHUSDT"
    genome = StrategyGenome(
        strategy_id="screen-exit-1",
        family="momentum",
        style="intraday",
        instruments=(instrument,),
        timeframe="1m",
        entry={"type": "rsi_momentum", "period": 3, "threshold": 55},
        exit={"type": "atr_bracket", "stop_atr": 3.0, "target_atr": 1.0, "atr_period": 3},
        allow_short=False,
    )
    bars = _bars_from_closes(
        instrument,
        [100.0, 101.0, 102.0, 103.0, 104.0, 110.0, 111.0, 112.0, 118.0, 119.0, 120.0],
    )

    result = screen_genome(genome, {instrument: bars}, fees=0.0, slippage=0.0)

    assert result.trade_count >= 2


def test_screen_genome_rejects_missing_instrument_data():
    genome = generate_candidate(family="breakout", instruments=("ETHUSDT",), seed=7)

    try:
        screen_genome(genome, {}, fees=0.0, slippage=0.0)
    except ValueError as exc:
        assert "instrument" in str(exc).lower()
    else:
        raise AssertionError("missing instrument data must fail closed")
