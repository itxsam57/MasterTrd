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
    """Return conservative closed-bar history needed before forward risk is created.

    The entry requirement is combined with rolling exit-state requirements so a
    strategy cannot open immediately after warm-up while its protective exit is
    still missing the history needed to evaluate on the next closed bar.
    """

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
    elif exit_kind in {"cross_reverse", "greeks_or_time_exit"}:
        pass
    elif exit_kind in {"spread_mean_exit", "edge_decay", "rebalance"}:
        # Multi-leg PAPER is not currently admitted, but research/execution
        # history sizing remains deterministic for those genomes.
        pass
    else:
        raise ValueError(f"unsupported exit kind for history bootstrap: {exit_kind}")
    if required <= 0:
        raise ValueError("required bar history must be positive")
    return required


def paper_bootstrap_bar_limit(genome: StrategyGenome) -> int:
    """Return the number of closed public bars loaded before PAPER starts.

    Keep a substantial buffer above the exact minimum so indicator state does
    not depend on a process having remained alive since strategy deployment.
    Binance's public kline endpoint caps one response at 1000 rows.
    """

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

    if len(bars) < required_bar_history_for_limit(limit, bars):
        raise RuntimeError("public Binance PAPER history returned too few closed bars")
    return tuple(bars)


def required_bar_history_for_limit(limit: int, bars: list[MarketBar]) -> int:
    """Validate that the public endpoint returned a useful closed-history window.

    The loader does not know the genome; the caller already chooses a limit at
    or above its required history. Requiring at least half the requested window
    catches truncated/malformed responses while tolerating newly listed markets.
    """

    if not bars:
        return 1
    return min(limit, max(1, limit // 2))
