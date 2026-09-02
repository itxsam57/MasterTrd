from __future__ import annotations

import math

import pytest

from mastertrd.micro_profit_2s import MicroProfit2sReport, evaluate_micro_profit_windows


SECOND_NS = 1_000_000_000


def test_micro_profit_report_requires_one_cent_in_every_non_overlapping_two_second_window() -> None:
    report = evaluate_micro_profit_windows(
        (
            (0, 100.000),
            (2 * SECOND_NS, 100.012),
            (4 * SECOND_NS, 100.020),
            (6 * SECOND_NS, 100.031),
        ),
        target_net_usd=0.01,
        window_seconds=2.0,
        synthetic=False,
    )

    assert report.window_net_pnl_usd == pytest.approx((0.012, 0.008, 0.011))
    assert report.window_count == 3
    assert report.hit_count == 2
    assert report.hit_rate == pytest.approx(2.0 / 3.0)
    assert report.mean_net_usd == pytest.approx(0.031 / 3.0)
    assert report.min_net_usd == pytest.approx(0.008)
    assert report.total_net_usd == pytest.approx(0.031)
    assert report.every_window_passed is False
    assert report.target_proven is False
    assert report.supporting_only is False


def test_synthetic_all_green_replay_is_supporting_only_not_profitability_proof() -> None:
    report = evaluate_micro_profit_windows(
        (
            (10 * SECOND_NS, 50.000),
            (12 * SECOND_NS, 50.011),
            (14 * SECOND_NS, 50.022),
            (16 * SECOND_NS, 50.033),
        ),
        target_net_usd=0.01,
        window_seconds=2.0,
        synthetic=True,
    )

    assert report.every_window_passed is True
    assert report.hit_rate == 1.0
    assert report.supporting_only is True
    assert report.target_proven is False


def _report(**overrides) -> MicroProfit2sReport:
    values = {
        "target_net_usd": 0.01,
        "window_seconds": 2.0,
        "window_net_pnl_usd": (0.011,),
        "window_count": 1,
        "hit_count": 1,
        "hit_rate": 1.0,
        "mean_net_usd": 0.011,
        "min_net_usd": 0.011,
        "total_net_usd": 0.011,
        "every_window_passed": True,
        "supporting_only": False,
        "target_proven": True,
    }
    values.update(overrides)
    return MicroProfit2sReport(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"target_net_usd": 0.0}, "target_net_usd"),
        ({"target_net_usd": math.inf}, "target_net_usd"),
        ({"window_seconds": 0.0}, "window_seconds"),
        ({"window_seconds": math.inf}, "window_seconds"),
        ({"window_count": 0, "window_net_pnl_usd": ()}, "window_count"),
        ({"window_count": 2}, "window_count"),
        ({"hit_count": -1}, "hit_count"),
        ({"hit_count": 2}, "hit_count"),
        ({"hit_rate": -0.1}, "hit_rate"),
        ({"hit_rate": 1.1}, "hit_rate"),
        ({"window_net_pnl_usd": (math.nan,)}, "window PnL"),
        ({"supporting_only": True}, "target proof"),
        ({"every_window_passed": False}, "target proof"),
    ),
)
def test_micro_profit_report_dataclass_fails_closed(overrides, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _report(**overrides)


def test_micro_profit_report_rejects_invalid_window_inputs() -> None:
    samples = ((0, 100.0), (2 * SECOND_NS, 100.01))

    with pytest.raises(ValueError, match="target_net_usd"):
        evaluate_micro_profit_windows(samples, target_net_usd=0.0)
    with pytest.raises(ValueError, match="target_net_usd must be finite"):
        evaluate_micro_profit_windows(samples, target_net_usd="not-a-number")
    with pytest.raises(ValueError, match="target_net_usd must be finite"):
        evaluate_micro_profit_windows(samples, target_net_usd=math.inf)
    with pytest.raises(ValueError, match="window_seconds"):
        evaluate_micro_profit_windows(samples, target_net_usd=0.01, window_seconds=0.0)
    with pytest.raises(ValueError, match="whole nanoseconds"):
        evaluate_micro_profit_windows(
            ((0, 100.0), (1, 100.01)),
            target_net_usd=0.01,
            window_seconds=1e-10,
        )
    with pytest.raises(ValueError, match="integer nanoseconds"):
        evaluate_micro_profit_windows(
            ((False, 100.0), (2 * SECOND_NS, 100.01)),
            target_net_usd=0.01,
        )
    with pytest.raises(ValueError, match="integer nanoseconds"):
        evaluate_micro_profit_windows(
            ((0.0, 100.0), (2 * SECOND_NS, 100.01)),
            target_net_usd=0.01,
        )
    with pytest.raises(ValueError, match="equity_usd must be finite"):
        evaluate_micro_profit_windows(
            ((0, math.nan), (2 * SECOND_NS, 100.01)),
            target_net_usd=0.01,
        )


def test_micro_profit_report_rejects_sparse_or_non_monotonic_equity_samples() -> None:
    with pytest.raises(ValueError, match="at least two equity samples"):
        evaluate_micro_profit_windows(((0, 100.0),), target_net_usd=0.01)

    with pytest.raises(ValueError, match="strictly increasing"):
        evaluate_micro_profit_windows(
            ((0, 100.0), (2 * SECOND_NS, 100.01), (2 * SECOND_NS, 100.02)),
            target_net_usd=0.01,
        )

    with pytest.raises(ValueError, match="exact window boundaries"):
        evaluate_micro_profit_windows(
            ((0, 100.0), (SECOND_NS, 100.01), (3 * SECOND_NS, 100.02)),
            target_net_usd=0.01,
        )
