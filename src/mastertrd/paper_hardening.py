from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isfinite
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from .contracts import MarketBar
from .genome import StrategyGenome


_MAX_BINANCE_KLINES = 1000
_MIN_BOOTSTRAP_BARS = 100
_SUPPORTED_INTERVALS = frozenset(
    {"1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
)


def _positive_int(value: object, *, name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _positive_float(value: object, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be positive and finite") from exc
    if not isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be positive and finite")
    return result


def validate_bar_strategy_contract(genome: StrategyGenome) -> None:
    """Fail closed on malformed single-leg BAR entry/exit semantics at compile time."""

    kind = str(genome.entry.get("kind", genome.entry.get("type", "")))
    if not kind:
        raise ValueError("strategy entry kind is required")
    if kind == "ema_cross":
        fast = _positive_int(
            genome.entry.get("fast_period", genome.entry.get("fast")),
            name="fast_period",
        )
        slow = _positive_int(
            genome.entry.get("slow_period", genome.entry.get("slow")),
            name="slow_period",
        )
        if fast >= slow:
            raise ValueError("fast_period must be less than slow_period")
    elif kind == "rsi_momentum":
        _positive_int(genome.entry.get("period"), name="period")
        threshold = _positive_float(genome.entry.get("threshold"), name="threshold")
        if threshold <= 50.0 or threshold > 100.0:
            raise ValueError("threshold must be greater than 50 and at most 100")
    elif kind == "donchian_breakout":
        _positive_int(genome.entry.get("window"), name="window")
    elif kind == "zscore_reversion":
        window = _positive_int(genome.entry.get("window"), name="window")
        if window < 2:
            raise ValueError("zscore window must be at least two")
        _positive_float(genome.entry.get("z"), name="z")
    elif kind == "volatility_breakout":
        _positive_int(genome.entry.get("lookback"), name="lookback")
        _positive_float(genome.entry.get("multiplier"), name="multiplier")
    elif kind == "pullback_trend":
        fast = _positive_int(genome.entry.get("fast"), name="fast")
        slow = _positive_int(genome.entry.get("slow"), name="slow")
        if fast >= slow:
            raise ValueError("fast must be less than slow")
        _positive_int(genome.entry.get("rsi"), name="rsi")
    elif kind == "long_horizon_trend":
        fast = _positive_int(genome.entry.get("fast"), name="fast")
        slow = _positive_int(genome.entry.get("slow"), name="slow")
        if fast >= slow:
            raise ValueError("fast must be less than slow")
    elif kind in {"cointegration_spread", "strategy_rotation"}:
        _positive_int(
            genome.entry.get("window", genome.entry.get("lookback")),
            name="window",
        )
    elif kind in {"funding_basis", "hedged_basis", "volatility_signal"}:
        # Specialist data/state is validated by those execution paths.
        pass
    else:
        raise ValueError(f"unsupported bar entry kind: {kind}")

    exit_kind = str(genome.exit.get("kind", genome.exit.get("type", "")))
    if not exit_kind:
        raise ValueError("strategy exit policy is required")
    if exit_kind == "cross_reverse":
        return
    if exit_kind == "atr_bracket":
        _positive_float(genome.exit.get("stop_atr"), name="stop_atr")
        _positive_float(genome.exit.get("target_atr"), name="target_atr")
        _positive_int(genome.exit.get("atr_period", 14), name="atr_period")
        return
    if exit_kind == "mean_or_atr_stop":
        _positive_float(genome.exit.get("stop_atr"), name="stop_atr")
        _positive_int(genome.exit.get("atr_period", 14), name="atr_period")
        return
    if exit_kind == "trailing_atr":
        _positive_float(genome.exit.get("atr"), name="atr")
        _positive_int(genome.exit.get("atr_period", 14), name="atr_period")
        return
    if exit_kind in {"greeks_or_time_exit", "spread_mean_exit", "edge_decay", "rebalance"}:
        # These belong to specialist/multi-leg execution paths and are retained
        # here only so history sizing remains deterministic when called there.
        return
    raise ValueError(f"unsupported exit policy: {exit_kind}")


def _entry_bar_requirement(genome: StrategyGenome) -> int:
    kind = str(genome.entry.get("kind", genome.entry.get("type", "")))
    if kind == "ema_cross":
        return int(genome.entry.get("slow_period", genome.entry.get("slow", 0)))
    if kind == "rsi_momentum":
        return int(genome.entry["period"]) + 1
    if kind in {"donchian_breakout", "zscore_reversion"}:
        return int(genome.entry["window"]) + 1
    if kind == "volatility_breakout":
        return int(genome.entry["lookback"]) + 1
    if kind == "pullback_trend":
        return max(int(genome.entry["slow"]), int(genome.entry["rsi"]) + 1)
    if kind == "long_horizon_trend":
        return int(genome.entry["slow"])
    if kind == "cointegration_spread":
        return int(genome.entry["window"]) + 1
    if kind == "strategy_rotation":
        return int(genome.entry["lookback"]) + 1
    if kind in {"funding_basis", "hedged_basis", "volatility_signal"}:
        return 1
    raise ValueError(f"unsupported bar entry kind for history bootstrap: {kind}")


def required_bar_history(genome: StrategyGenome) -> int:
    """Return conservative closed-bar history needed before forward risk is created."""

    validate_bar_strategy_contract(genome)
    required = _entry_bar_requirement(genome)
    exit_kind = str(genome.exit.get("kind", genome.exit.get("type", "")))
    if exit_kind in {"atr_bracket", "trailing_atr"}:
        required = max(required, int(genome.exit.get("atr_period", 14)) + 1)
    elif exit_kind == "mean_or_atr_stop":
        required = max(
            required,
            int(genome.entry.get("window", 0)) + 1,
            int(genome.exit.get("atr_period", 14)) + 1,
        )
    if required <= 0:
        raise ValueError("required bar history must be positive")
    return required


def paper_bootstrap_bar_limit(genome: StrategyGenome) -> int:
    """Return the number of closed public bars loaded before PAPER starts."""

    return min(_MAX_BINANCE_KLINES, max(_MIN_BOOTSTRAP_BARS, required_bar_history(genome) + 10))


def _finite_number(value: object, *, name: str, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Binance history {name} is invalid") from exc
    if not isfinite(number) or (positive and number <= 0.0):
        raise RuntimeError(f"Binance history {name} is invalid")
    return number


def load_public_binance_bar_history(
    instrument_id: str,
    timeframe: str,
    *,
    limit: int,
    now_ms: int | None = None,
) -> tuple[MarketBar, ...]:
    """Load recent *closed* Binance spot klines without credentials.

    This is a fail-closed PAPER bootstrap path. It never authenticates, never
    falls back to synthetic data, and excludes the current in-progress candle.
    The caller owns the candidate-specific minimum history check.
    """

    raw_instrument = str(instrument_id).strip().upper()
    if not raw_instrument.endswith(".BINANCE"):
        raise RuntimeError("public PAPER history requires a BINANCE instrument")
    symbol = raw_instrument.rsplit(".", 1)[0]
    interval = str(timeframe).strip()
    if interval not in _SUPPORTED_INTERVALS:
        raise RuntimeError(f"unsupported Binance history timeframe: {timeframe}")
    if limit <= 0 or limit > _MAX_BINANCE_KLINES:
        raise ValueError("Binance history limit must be between 1 and 1000")

    query = urlencode({"symbol": symbol, "interval": interval, "limit": int(limit)})
    url = f"https://data-api.binance.vision/api/v3/klines?{query}"
    try:
        with urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("public Binance PAPER history could not be loaded") from exc
    if not isinstance(payload, list):
        raise RuntimeError("public Binance PAPER history response is invalid")

    cutoff_ms = int(time.time() * 1000.0) if now_ms is None else int(now_ms)
    bars: list[MarketBar] = []
    previous_close_ms = -1
    for raw in payload:
        if not isinstance(raw, list) or len(raw) < 7:
            raise RuntimeError("public Binance PAPER history row is invalid")
        try:
            close_ms = int(raw[6])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("public Binance PAPER history timestamp is invalid") from exc
        if close_ms >= cutoff_ms:
            continue
        if close_ms <= previous_close_ms:
            raise RuntimeError("public Binance PAPER history is not strictly ordered")
        open_price = _finite_number(raw[1], name="open", positive=True)
        high = _finite_number(raw[2], name="high", positive=True)
        low = _finite_number(raw[3], name="low", positive=True)
        close = _finite_number(raw[4], name="close", positive=True)
        volume = _finite_number(raw[5], name="volume")
        if volume < 0.0:
            raise RuntimeError("public Binance PAPER history volume is invalid")
        bars.append(
            MarketBar(
                timestamp=datetime.fromtimestamp(close_ms / 1000.0, tz=timezone.utc),
                venue="BINANCE",
                instrument=raw_instrument,
                timeframe=interval,
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
                extras={"source_kline_close_ms": close_ms, "bootstrap": True},
            )
        )
        previous_close_ms = close_ms

    if not bars:
        raise RuntimeError("public Binance PAPER history returned no closed bars")
    return tuple(bars)
