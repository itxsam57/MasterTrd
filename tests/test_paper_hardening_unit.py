from __future__ import annotations

import json

import pytest

from mastertrd.genome import StrategyGenome
import mastertrd.paper_hardening as hardening


def genome(entry: dict, exit_rule: dict) -> StrategyGenome:
    return StrategyGenome(
        strategy_id="paper-hardening-unit",
        family="trend",
        style="test",
        instruments=("ETHUSDT.BINANCE",),
        timeframe="15m",
        entry=entry,
        exit=exit_rule,
        allow_short=True,
    )


@pytest.mark.parametrize(
    ("entry", "exit_rule", "expected"),
    [
        ({"kind": "ema_cross", "fast": 11, "slow": 34}, {"kind": "cross_reverse"}, 34),
        ({"kind": "rsi_momentum", "period": 14, "threshold": 60}, {"kind": "atr_bracket", "stop_atr": 2, "target_atr": 3}, 15),
        ({"kind": "donchian_breakout", "window": 20}, {"kind": "atr_bracket", "stop_atr": 2, "target_atr": 3}, 21),
        ({"kind": "zscore_reversion", "window": 20, "z": 2}, {"kind": "mean_or_atr_stop", "stop_atr": 2}, 21),
        ({"kind": "volatility_breakout", "lookback": 30, "multiplier": 1.5}, {"kind": "atr_bracket", "stop_atr": 2, "target_atr": 3}, 31),
        ({"kind": "pullback_trend", "fast": 10, "slow": 30, "rsi": 14}, {"kind": "atr_bracket", "stop_atr": 2, "target_atr": 3}, 30),
        ({"kind": "long_horizon_trend", "fast": 20, "slow": 100}, {"kind": "trailing_atr", "atr": 2}, 100),
        ({"kind": "cointegration_spread", "window": 60}, {"kind": "spread_mean_exit"}, 61),
        ({"kind": "strategy_rotation", "lookback": 50}, {"kind": "rebalance"}, 51),
        ({"kind": "funding_basis"}, {"kind": "edge_decay"}, 1),
        ({"kind": "hedged_basis"}, {"kind": "rebalance"}, 1),
        ({"kind": "volatility_signal"}, {"kind": "greeks_or_time_exit"}, 1),
    ],
)
def test_required_bar_history_covers_supported_entry_exit_contracts(entry, exit_rule, expected):
    candidate = genome(entry, exit_rule)
    hardening.validate_bar_strategy_contract(candidate)
    assert hardening.required_bar_history(candidate) == expected
    assert hardening.paper_bootstrap_bar_limit(candidate) >= max(100, expected)


@pytest.mark.parametrize(
    ("entry", "exit_rule", "message"),
    [
        ({"kind": "ema_cross", "fast": "bad", "slow": 34}, {"kind": "cross_reverse"}, "fast_period"),
        ({"kind": "ema_cross", "fast": 0, "slow": 34}, {"kind": "cross_reverse"}, "fast_period"),
        ({"kind": "ema_cross", "fast": 34, "slow": 34}, {"kind": "cross_reverse"}, "less than"),
        ({"kind": "rsi_momentum", "period": 14, "threshold": 50}, {"kind": "cross_reverse"}, "threshold"),
        ({"kind": "rsi_momentum", "period": 14, "threshold": float("inf")}, {"kind": "cross_reverse"}, "threshold"),
        ({"kind": "zscore_reversion", "window": 1, "z": 2}, {"kind": "mean_or_atr_stop", "stop_atr": 2}, "at least two"),
        ({"kind": "pullback_trend", "fast": 30, "slow": 20, "rsi": 14}, {"kind": "cross_reverse"}, "fast must be less"),
        ({"kind": "long_horizon_trend", "fast": 100, "slow": 100}, {"kind": "trailing_atr", "atr": 2}, "fast must be less"),
        ({"kind": "unknown_signal"}, {"kind": "cross_reverse"}, "unsupported bar entry"),
        ({"foo": "bar"}, {"kind": "cross_reverse"}, "entry kind"),
        ({"kind": "ema_cross", "fast": 11, "slow": 34}, {"foo": "exit"}, "exit policy"),
        ({"kind": "ema_cross", "fast": 11, "slow": 34}, {"kind": "atr_bracket", "stop_atr": 0, "target_atr": 3}, "stop_atr"),
        ({"kind": "ema_cross", "fast": 11, "slow": 34}, {"kind": "trailing_atr", "atr": "bad"}, "atr"),
        ({"kind": "ema_cross", "fast": 11, "slow": 34}, {"kind": "unknown_exit"}, "unsupported exit"),
    ],
)
def test_bar_strategy_contract_rejects_invalid_values(entry, exit_rule, message):
    with pytest.raises(ValueError, match=message):
        hardening.validate_bar_strategy_contract(genome(entry, exit_rule))


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _history(monkeypatch, payload, *, now_ms=2_000_000):
    monkeypatch.setattr(hardening, "urlopen", lambda *_args, **_kwargs: Response(payload))
    return hardening.load_public_binance_bar_history(
        "ETHUSDT.BINANCE",
        "15m",
        limit=2,
        now_ms=now_ms,
    )


def test_history_loader_rejects_bad_identity_timeframe_and_limit():
    with pytest.raises(RuntimeError, match="BINANCE instrument"):
        hardening.load_public_binance_bar_history("ETHUSDT.OTHER", "15m", limit=2)
    with pytest.raises(RuntimeError, match="timeframe"):
        hardening.load_public_binance_bar_history("ETHUSDT.BINANCE", "7m", limit=2)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        hardening.load_public_binance_bar_history("ETHUSDT.BINANCE", "15m", limit=0)


def test_history_loader_fails_closed_on_network_and_shape_errors(monkeypatch):
    monkeypatch.setattr(hardening, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(RuntimeError, match="could not be loaded"):
        hardening.load_public_binance_bar_history("ETHUSDT.BINANCE", "15m", limit=2)

    monkeypatch.setattr(hardening, "urlopen", lambda *_args, **_kwargs: Response({"bad": "shape"}))
    with pytest.raises(RuntimeError, match="response is invalid"):
        hardening.load_public_binance_bar_history("ETHUSDT.BINANCE", "15m", limit=2)


def test_history_loader_rejects_malformed_rows(monkeypatch):
    with pytest.raises(RuntimeError, match="row is invalid"):
        _history(monkeypatch, [[1, "100"]])
    with pytest.raises(RuntimeError, match="timestamp is invalid"):
        _history(monkeypatch, [[0, "100", "101", "99", "100", "1", "bad"]])
    with pytest.raises(RuntimeError, match="strictly ordered"):
        _history(
            monkeypatch,
            [
                [0, "100", "101", "99", "100", "1", 899_999],
                [1, "100", "101", "99", "100", "1", 899_999],
            ],
        )
    with pytest.raises(RuntimeError, match="open is invalid"):
        _history(monkeypatch, [[0, "bad", "101", "99", "100", "1", 899_999]])
    with pytest.raises(RuntimeError, match="volume is invalid"):
        _history(monkeypatch, [[0, "100", "101", "99", "100", "-1", 899_999]])


def test_history_loader_excludes_open_candle_and_requires_closed_history(monkeypatch):
    with pytest.raises(RuntimeError, match="no closed bars"):
        _history(
            monkeypatch,
            [[0, "100", "101", "99", "100", "1", 2_000_000]],
            now_ms=2_000_000,
        )
