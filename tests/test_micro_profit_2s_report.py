from __future__ import annotations

import pytest

from mastertrd.micro_profit_2s import evaluate_micro_profit_windows


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
