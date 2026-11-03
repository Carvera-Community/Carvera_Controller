"""Time-window smoothing of the per-vertex MRR."""

import numpy as np
import pytest

from carveracontroller.addons.stock.mrr_smoothing import smooth_mrr_at, smooth_mrr_series
from carveracontroller.ui.file_sim_info.summary import summarize_file_sim


def _series(rate, durations, valid=None, window=1.0):
    rate = np.asarray(rate, dtype=np.float64)
    durations = np.asarray(durations, dtype=np.float64)
    if valid is None:
        valid = np.ones(rate.shape[0], dtype=bool)
        valid[0] = False
    return smooth_mrr_series(rate, durations, valid, window)


def test_quantized_short_moves_average_to_the_true_rate():
    # 100 moves of 10 ms. One 1 mm³ cube is removed every 10th move: 600 mm³/min on
    # average, but reading each move alone swings between 0 and 6000.
    count = 101
    rate = np.zeros(count)
    rate[10::10] = 6000.0
    durations = np.full(count, 0.01)
    durations[0] = 0.0
    smoothed = _series(rate, durations)
    assert rate.max() == 6000.0
    assert smoothed[-1] == pytest.approx(600.0)


def test_window_is_trailing_and_interpolates_partial_moves():
    # 0.6 s at 100 then 0.6 s at 400. The 1 s window ending at the last move covers 0.4 s of the first.
    smoothed = _series([0.0, 100.0, 400.0], [0.0, 0.6, 0.6])
    assert smoothed[1] == pytest.approx(100.0)
    assert smoothed[2] == pytest.approx((100.0 * 0.4 + 400.0 * 0.6) / 1.0)


def test_window_skips_rapids_without_restarting():
    # Two cuts at 900 and 30 separated by a 5 s rapid. The rapid adds no time to the window,
    # so the second cut is averaged with the end of the first one.
    valid = np.array([False, True, False, True])
    smoothed = _series([0.0, 900.0, 0.0, 30.0], [0.0, 0.5, 5.0, 0.5], valid)
    assert smoothed[1] == pytest.approx(900.0)
    assert smoothed[2] == 0.0
    assert smoothed[3] == pytest.approx((900.0 * 0.5 + 30.0 * 0.5) / 1.0)


def test_window_does_not_cross_a_tool_change():
    valid = np.array([False, True, False, True])
    groups = np.array([1, 1, 1, 2])
    smoothed = smooth_mrr_series(
        np.array([0.0, 900.0, 0.0, 30.0]),
        np.array([0.0, 0.5, 5.0, 0.5]),
        valid,
        1.0,
        groups,
    )
    assert smoothed[3] == pytest.approx(30.0)


def test_unmeasured_moves_stay_nan_and_add_nothing():
    smoothed = _series([0.0, 60.0, np.nan, 60.0], [0.0, 0.5, 0.5, 0.5])
    assert np.isnan(smoothed[2])
    assert smoothed[3] == pytest.approx(60.0)


def test_zero_window_returns_raw():
    raw = [0.0, 10.0, 90.0]
    np.testing.assert_array_equal(_series(raw, [0.0, 0.1, 0.1], window=0.0), raw)


def test_single_vertex_matches_the_series():
    rng = np.random.default_rng(3)
    count = 400
    rate = rng.choice([0.0, 0.0, 250.0, 4000.0], size=count)
    rate[17] = np.nan
    durations = rng.uniform(0.001, 0.08, size=count)
    durations[0] = 0.0
    valid = rng.random(count) > 0.05
    valid[0] = False
    groups = np.repeat([1, 2, 1, 3], count // 4)
    expected = smooth_mrr_series(rate, durations, valid, 1.0, groups)
    for index in (1, 2, 50, 123, 399):
        got = smooth_mrr_at(
            rate,
            index,
            1.0,
            lambda i: float(durations[i]),
            lambda i: bool(valid[i]),
            lambda i: int(groups[i]),
        )
        if np.isnan(expected[index]):
            assert got is None
        else:
            assert got == pytest.approx(float(expected[index]))


def test_summary_peak_uses_the_window_but_volume_stays_raw():
    count = 101
    positions = [coord for index in range(count) for coord in (float(index), 0.0, 0.0)]
    rate = np.zeros(count)
    rate[10::10] = 6000.0
    line_times = [index * 0.01 for index in range(count)]
    kwargs = {
        "positions": positions,
        "mrr": rate,
        "line_times": line_times,
        "vertex_types": [1.0] * count,
        "tools": [1] * count,
    }
    smooth = summarize_file_sim(**kwargs)
    raw = summarize_file_sim(smooth_window_sec=0.0, **kwargs)

    assert raw.peak_mrr == 6000.0
    assert smooth.peak_mrr == pytest.approx(600.0, rel=0.15)
    assert smooth.removed_volume_mm3 == raw.removed_volume_mm3
    assert smooth.average_cutting_mrr == raw.average_cutting_mrr
    assert float(np.nanmax(smooth.chart_series[0].mrr)) < 1000.0
