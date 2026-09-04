from __future__ import annotations

import pytest

from mastertrd.bar_completeness import BarCompletenessSnapshot
from mastertrd.public_market_canary import run_public_binance_closed_bar_canary


def test_public_binance_canary_targets_current_minute_and_requires_complete_close():
    now_seconds = 1_788_436_812.345
    anchor_ms = (int(now_seconds * 1_000) // 60_000) * 60_000
    target_close_ms = anchor_ms + 59_999
    captured: dict[str, object] = {}

    class FakeSource:
        def __init__(self, instruments, **kwargs):
            captured["instruments"] = tuple(instruments)
            captured.update(kwargs)
            self.completeness_snapshot = BarCompletenessSnapshot(
                expected_closed_bars=0,
                ws_closed_bars=0,
                rest_recovered_bars=0,
                missing_closed_bars=0,
                recovery_failures=0,
                last_closed_bar_ms=None,
                last_expected_close_ms=None,
                last_recovery_error=None,
                data_healthy=True,
            )

        def __iter__(self):
            self.completeness_snapshot = BarCompletenessSnapshot(
                expected_closed_bars=1,
                ws_closed_bars=1,
                rest_recovered_bars=0,
                missing_closed_bars=0,
                recovery_failures=0,
                last_closed_bar_ms=target_close_ms,
                last_expected_close_ms=target_close_ms,
                last_recovery_error=None,
                data_healthy=True,
            )
            yield {"event_id": "closed-bar"}

    result = run_public_binance_closed_bar_canary(
        clock=lambda: now_seconds,
        source_factory=FakeSource,
    )

    assert captured["instruments"] == ("ETHUSDT.BINANCE",)
    assert captured["timeframe"] == "1m"
    assert captured["first_expected_start_ms"] == anchor_ms
    assert captured["recovery_grace_ms"] == 3_000
    assert captured["max_reconnect_attempts"] == 1
    assert result["target_close_ms"] == target_close_ms
    assert result["expected_closed_bars"] == 1
    assert result["ws_closed_bars"] == 1
    assert result["rest_recovered_bars"] == 0
    assert result["missing_closed_bars"] == 0
    assert result["data_healthy"] is True


def test_public_binance_canary_fails_closed_on_incomplete_target_candle():
    now_seconds = 1_788_436_812.345
    anchor_ms = (int(now_seconds * 1_000) // 60_000) * 60_000
    target_close_ms = anchor_ms + 59_999

    class UnhealthySource:
        def __init__(self, _instruments, **_kwargs):
            self.completeness_snapshot = None

        def __iter__(self):
            self.completeness_snapshot = BarCompletenessSnapshot(
                expected_closed_bars=1,
                ws_closed_bars=0,
                rest_recovered_bars=0,
                missing_closed_bars=1,
                recovery_failures=1,
                last_closed_bar_ms=None,
                last_expected_close_ms=target_close_ms,
                last_recovery_error="RuntimeError:public Binance closed candle could not be recovered",
                data_healthy=False,
            )
            yield {"event_id": "newer-book-tick"}

    with pytest.raises(RuntimeError, match="closed-bar canary.*unhealthy"):
        run_public_binance_closed_bar_canary(
            clock=lambda: now_seconds,
            source_factory=UnhealthySource,
        )
