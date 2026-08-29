from __future__ import annotations

import random
from hashlib import sha256
from typing import Sequence

from mastertrd.genome import StrategyGenome
from mastertrd.strategy_families import DataLevel, family_spec


_TIMEFRAMES = {
    "trend": ("15m", "1h", "4h"),
    "momentum": ("5m", "15m", "1h"),
    "breakout": ("5m", "15m", "1h"),
    "mean_reversion": ("5m", "15m", "1h"),
    "volatility": ("15m", "1h", "4h"),
    "swing": ("1h", "4h", "1d"),
    "position": ("4h", "1d"),
    "stat_arb": ("15m", "1h", "4h"),
    "funding_basis": ("1h", "4h"),
    "delta_neutral": ("1h", "4h"),
    "options": ("1h", "4h", "1d"),
    "portfolio": ("1h", "4h", "1d"),
    "scalping": ("tick", "1m"),
    "grid": ("tick", "1m"),
    "market_making": ("tick",),
    "order_book": ("tick",),
    "cross_venue_arb": ("tick",),
}


def _rules(family: str, rng: random.Random) -> tuple[dict, dict, dict]:
    fast = rng.randint(5, 24)
    slow = rng.randint(max(fast + 5, 20), 120)
    rsi = rng.randint(7, 21)
    atr = round(rng.uniform(1.0, 3.5), 2)
    common_exit = {"type": "atr_bracket", "stop_atr": atr, "target_atr": round(atr * rng.uniform(1.2, 2.5), 2)}

    rules = {
        # Stable Nautilus v1 ships a real EMACross strategy whose exit semantic is
        # crossover reversal. Keep this baseline honest rather than pretending the
        # built-in strategy implements an ATR bracket it does not have.
        "trend": ({"type": "ema_cross", "fast": fast, "slow": slow}, {"type": "cross_reverse"}, {"adx_min": rng.randint(15, 30)}),
        "momentum": ({"type": "rsi_momentum", "period": rsi, "threshold": rng.randint(52, 68)}, common_exit, {"volume_confirm": True}),
        "breakout": ({"type": "donchian_breakout", "window": rng.randint(10, 80)}, common_exit, {"atr_min": round(rng.uniform(0.2, 2.0), 2)}),
        "mean_reversion": ({"type": "zscore_reversion", "window": rng.randint(12, 80), "z": round(rng.uniform(1.2, 3.0), 2)}, {"type": "mean_or_atr_stop", "stop_atr": atr}, {"rsi_period": rsi}),
        "volatility": ({"type": "volatility_breakout", "lookback": rng.randint(10, 60), "multiplier": round(rng.uniform(1.0, 3.0), 2)}, common_exit, {"garch_filter": True}),
        "swing": ({"type": "pullback_trend", "fast": fast, "slow": slow, "rsi": rsi}, common_exit, {"multi_timeframe": True}),
        "position": ({"type": "long_horizon_trend", "fast": rng.randint(20, 80), "slow": rng.randint(100, 300)}, {"type": "trailing_atr", "atr": atr}, {"volatility_target": round(rng.uniform(0.08, 0.25), 3)}),
        "stat_arb": ({"type": "cointegration_spread", "window": rng.randint(60, 240), "z_entry": round(rng.uniform(1.0, 3.0), 2)}, {"type": "spread_mean_exit", "z_exit": round(rng.uniform(0.0, 0.8), 2)}, {"max_pvalue": 0.05}),
        "funding_basis": ({"type": "funding_basis", "min_edge_bps": rng.randint(5, 50)}, {"type": "edge_decay", "exit_bps": rng.randint(1, 10)}, {"delta_neutral": True}),
        "delta_neutral": ({"type": "hedged_basis", "hedge_ratio": round(rng.uniform(0.9, 1.1), 3)}, {"type": "rebalance", "drift_bps": rng.randint(10, 100)}, {"delta_target": 0.0}),
        "options": ({"type": "volatility_signal", "iv_rv_ratio": round(rng.uniform(0.7, 1.5), 2)}, {"type": "greeks_or_time_exit", "max_days": rng.randint(1, 30)}, {"defined_risk_only": True}),
        "portfolio": ({"type": "strategy_rotation", "lookback": rng.randint(20, 120)}, {"type": "rebalance", "periods": rng.randint(1, 20)}, {"volatility_target": round(rng.uniform(0.08, 0.25), 3)}),
        "scalping": ({"type": "micro_momentum", "ticks": rng.randint(5, 80)}, {"type": "ticks_or_timeout", "stop_ticks": rng.randint(2, 15), "target_ticks": rng.randint(2, 25)}, {"spread_max_ticks": rng.randint(1, 5)}),
        "grid": ({"type": "dynamic_grid", "levels": rng.randint(3, 20), "spacing_bps": rng.randint(2, 50)}, {"type": "inventory_exit", "max_inventory": round(rng.uniform(0.1, 1.0), 2)}, {"volatility_adjusted": True}),
        "market_making": ({"type": "inventory_skew_mm", "half_spread_bps": rng.randint(1, 30)}, {"type": "inventory_flatten", "max_inventory": round(rng.uniform(0.1, 1.0), 2)}, {"queue_aware": True}),
        "order_book": ({"type": "order_book_imbalance", "levels": rng.randint(1, 20), "threshold": round(rng.uniform(0.05, 0.6), 3)}, {"type": "imbalance_reversal_or_ticks", "ticks": rng.randint(2, 20)}, {"queue_aware": True}),
        "cross_venue_arb": ({"type": "cross_venue_spread", "min_edge_bps": rng.randint(2, 40)}, {"type": "spread_convergence", "exit_bps": rng.randint(0, 10)}, {"simultaneous_hedge": True}),
    }
    return rules[family]


def generate_candidate(*, family: str, instruments: Sequence[str], seed: int) -> StrategyGenome:
    spec = family_spec(family)
    if not instruments:
        raise ValueError("at least one instrument is required")
    rng = random.Random(seed)
    entry, exit_rule, filters = _rules(family, rng)
    timeframe = rng.choice(_TIMEFRAMES[family])
    raw_id = f"{family}|{','.join(instruments)}|{seed}|{entry}|{exit_rule}|{filters}"
    strategy_id = "S-" + sha256(raw_id.encode()).hexdigest()[:12].upper()
    data_requirements = (spec.min_data_level.value,)
    if spec.min_data_level is DataLevel.BAR:
        data_requirements = ("BAR",)
    return StrategyGenome(
        strategy_id=strategy_id,
        family=family,
        style=family,
        instruments=tuple(instruments),
        timeframe=timeframe,
        entry=entry,
        exit=exit_rule,
        filters=filters,
        risk={
            "risk_fraction": round(rng.uniform(0.001, 0.01), 4),
            "max_drawdown_stop": round(rng.uniform(0.05, 0.25), 3),
        },
        data_requirements=data_requirements,
        allow_short=spec.supports_short,
    )
