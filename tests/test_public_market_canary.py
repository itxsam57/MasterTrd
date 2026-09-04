from __future__ import annotations

import json
from pathlib import Path

import pytest

from mastertrd.bar_completeness import BarCompletenessSnapshot
from mastertrd.public_market_canary import run_public_binance_closed_bar_canary


def test_public_binance_canary_requires_three_consecutive_complete_closes(tmp_path):
    now_seconds = 1_788_436_812.345
    anchor_ms = (int(now_seconds * 1_000) // 60_000) * 60_000
    target_close_ms = anchor_ms + (3 * 60_000) - 1
    captured: dict[str, object] = {}
    receipt_path = tmp_path / "canary-receipt.json"

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
            for count in (1, 2, 3):
                close_ms = anchor_ms + (count * 60_000) - 1
                self.completeness_snapshot = BarCompletenessSnapshot(
                    expected_closed_bars=count,
                    ws_closed_bars=count,
                    rest_recovered_bars=0,
                    missing_closed_bars=0,
                    recovery_failures=0,
                    last_closed_bar_ms=close_ms,
                    last_expected_close_ms=close_ms,
                    last_recovery_error=None,
                    data_healthy=True,
                )
                yield {"event_id": f"closed-bar-{count}"}

    result = run_public_binance_closed_bar_canary(
        clock=lambda: now_seconds,
        source_factory=FakeSource,
        receipt_path=receipt_path,
    )

    assert captured["instruments"] == ("ETHUSDT.BINANCE",)
    assert captured["timeframe"] == "1m"
    assert captured["first_expected_start_ms"] == anchor_ms
    assert captured["recovery_grace_ms"] == 3_000
    assert captured["max_reconnect_attempts"] == 1
    assert result["required_closed_bars"] == 3
    assert result["target_start_ms"] == anchor_ms
    assert result["target_close_ms"] == target_close_ms
    assert result["expected_closed_bars"] == 3
    assert result["ws_closed_bars"] == 3
    assert result["rest_recovered_bars"] == 0
    assert result["missing_closed_bars"] == 0
    assert result["data_healthy"] is True
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == result


def test_public_binance_canary_fails_closed_on_gap_before_third_close(tmp_path):
    now_seconds = 1_788_436_812.345
    anchor_ms = (int(now_seconds * 1_000) // 60_000) * 60_000
    target_close_ms = anchor_ms + (3 * 60_000) - 1
    receipt_path = tmp_path / "failed-receipt.json"

    class UnhealthySource:
        def __init__(self, _instruments, **_kwargs):
            self.completeness_snapshot = None

        def __iter__(self):
            self.completeness_snapshot = BarCompletenessSnapshot(
                expected_closed_bars=3,
                ws_closed_bars=2,
                rest_recovered_bars=0,
                missing_closed_bars=1,
                recovery_failures=1,
                last_closed_bar_ms=target_close_ms,
                last_expected_close_ms=target_close_ms,
                last_recovery_error="RuntimeError:public Binance closed candle could not be recovered",
                data_healthy=False,
            )
            yield {"event_id": "newer-book-tick"}

    with pytest.raises(RuntimeError, match="closed-bar canary.*unhealthy"):
        run_public_binance_closed_bar_canary(
            clock=lambda: now_seconds,
            source_factory=UnhealthySource,
            receipt_path=receipt_path,
        )
    assert not receipt_path.exists()


def test_public_binance_canary_workflow_is_bounded_credential_free_and_non_live():
    path = Path(".github/workflows/public-binance-canary.yml")
    assert path.exists()
    workflow = path.read_text(encoding="utf-8")

    required = (
        "workflow_dispatch:",
        "schedule:",
        "cron:",
        "push:",
        "src/mastertrd/public_market_canary.py",
        "src/mastertrd/binance_stream.py",
        "src/mastertrd/bar_completeness.py",
        "tests/test_public_market_canary.py",
        ".github/workflows/public-binance-canary.yml",
        "permissions:",
        "contents: read",
        "timeout-minutes: 5",
        "python-version: '3.13'",
        "uv==0.12.7",
        "uv lock --check",
        "uv sync --locked --all-extras",
        "uv pip check",
        "MASTERTRD_MODE: PAPER",
        "LIVE_TRADING_ENABLED: 'false'",
        "MASTERTRD_CANARY_RECEIPT:",
        "uv run python -m mastertrd.public_market_canary",
        "actions/upload-artifact@v4",
        "public-binance-canary-receipt.json",
    )
    for token in required:
        assert token in workflow

    forbidden = (
        "secrets.",
        "environment: oracle",
        "MASTERTRD_MODE: LIVE",
        "LIVE_TRADING_ENABLED: 'true'",
        "systemctl",
        "oracle-deploy",
    )
    for token in forbidden:
        assert token not in workflow
