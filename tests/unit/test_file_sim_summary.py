"""File summary stats and the downsampled MRR series."""

from types import SimpleNamespace

import numpy as np
import pytest

from carveracontroller.GcodeViewer import GCodeViewer, _segment_duration_sec
from carveracontroller.ui.file_sim_info.summary import (
    MrrChartSeries,
    _vector_segment_seconds,
    mrr_at_time,
    summarize_file_sim,
    vertex_at_time,
)


def _cut_types(count):
    return [1.0] * count


def test_summary_volume_peak_and_time_weighted_average():
    # 10 s at 10 mm³/min, then 30 s at 30 mm³/min. Vertex 0 is not a move.
    positions = [0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 10.0, 40.0, 0.0]
    line_times = [0.0, 10.0, 40.0]
    mrr = [0.0, 10.0, 30.0]
    summary = summarize_file_sim(
        filename="pocket.nc",
        positions=positions,
        mrr=np.array(mrr),
        line_times=line_times,
        vertex_types=_cut_types(3),
        tools=[2, 2, 2],
    )

    assert summary.has_path is True
    assert summary.filename == "pocket.nc"
    assert summary.estimated_sec == 40.0
    assert summary.path_length_mm == 50.0
    assert summary.removed_volume_mm3 == (10.0 * 10.0 + 30.0 * 30.0) / 60.0
    assert summary.peak_mrr == pytest.approx(30.0)
    assert summary.average_cutting_mrr == (10.0 * 10.0 + 30.0 * 30.0) / 40.0
    assert summary.bake_coverage == 1.0
    assert [series.label for series in summary.chart_series] == ["T2"]
    assert summary.chart_series[0].mrr.shape == (3,)
    assert float(summary.chart_series[0].times_min[-1]) == 40.0 / 60.0


def test_nan_moves_are_left_out_of_volume_and_coverage():
    positions = [0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, -2.0]
    summary = summarize_file_sim(
        positions=positions,
        mrr=np.array([0.0, 60.0, np.nan]),
        line_times=[0.0, 60.0, 120.0],
        vertex_types=_cut_types(3),
        tools=[1, 1, 5],
    )

    assert summary.removed_volume_mm3 == 60.0
    assert summary.peak_mrr == 60.0
    assert summary.average_cutting_mrr == 60.0
    assert summary.bake_coverage == 0.5
    assert [series.label for series in summary.chart_series] == ["T1"]
    assert np.isnan(summary.chart_series[0].mrr).sum() == 0


def test_rapids_and_laser_are_not_unmeasured_cuts():
    summary = summarize_file_sim(
        positions=[0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0],
        mrr=np.array([0.0, 0.0, 0.0, np.nan]),
        line_times=[0.0, 1.0, 2.0, 3.0],
        vertex_types=[2.0, 2.0, 1.0, 1.0],
        tools=[1, 1, 8888, 1],
    )

    assert summary.bake_coverage == 0.0
    assert summary.removed_volume_mm3 == 0.0
    assert summary.peak_mrr == 0.0
    assert summary.average_cutting_mrr is None


def test_missing_line_times_keeps_the_estimate_unset():
    summary = summarize_file_sim(
        positions=[0.0, 0.0, 0.0, 60.0, 0.0, 0.0],
        mrr=np.array([0.0, 30.0]),
        feeds=[0.0, 60.0],
        vertex_types=_cut_types(2),
        tools=[1, 1],
    )

    assert summary.estimated_sec is None
    assert summary.removed_volume_mm3 == 30.0
    assert float(summary.chart_series[0].times_min[-1]) == 1.0


def test_no_mrr_leaves_removal_fields_empty():
    summary = summarize_file_sim(
        positions=[0.0, 0.0, 0.0, 5.0, 0.0, 0.0],
        line_times=[0.0, 2.0],
        vertex_types=_cut_types(2),
    )

    assert summary.has_path is True
    assert summary.estimated_sec == 2.0
    assert summary.path_length_mm == 5.0
    assert summary.removed_volume_mm3 is None
    assert summary.peak_mrr is None
    assert summary.average_cutting_mrr is None
    assert summary.bake_coverage is None
    assert summary.chart_series == ()


def test_empty_path():
    summary = summarize_file_sim(filename="missing.nc")

    assert summary.has_path is False
    assert summary.filename == "missing.nc"
    assert summary.path_length_mm is None
    assert summary.chart_series == ()


def test_vector_durations_match_segment_timing():
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [10.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [0.0, 10.0, 0.0],
            [2.0, 10.0, 0.0],
        ],
        dtype=np.float64,
    )
    feeds = [0.0, 300.0, 0.0, 120.0, 80.0, 6000.0]
    angles = [0.0, 0.0, 90.0, 180.0, 180.0, 200.0]
    limits = {"x": 100.0, "y": 3000.0, "z": 2000.0, "a": 1800.0, "seek": 2500.0}
    got = _vector_segment_seconds(points, feeds, angles, limits)
    expected = [
        _segment_duration_sec(points[index - 1], points[index], angles[index - 1], angles[index], feeds[index], limits)
        for index in range(1, len(points))
    ]
    np.testing.assert_allclose(got, expected)

    plain = _vector_segment_seconds(points[:2], [0.0, 300.0], None, None)
    assert plain[0] == _segment_duration_sec(points[0], points[1], 0.0, 0.0, 300.0, None)


def test_chart_splits_a_bin_when_the_tool_changes():
    count = 40
    positions = []
    for index in range(count):
        positions.extend((float(index), 0.0, 0.0))
    mrr = np.full(count, 10.0)
    mrr[8:] = 40.0
    summary = summarize_file_sim(
        positions=positions,
        mrr=mrr,
        line_times=list(range(count)),
        vertex_types=_cut_types(count),
        tools=[2] * 8 + [5] * (count - 8),
        chart_bins=1,
    )

    assert [series.label for series in summary.chart_series] == ["T2", "T5"]
    assert float(np.nanmax(summary.chart_series[0].mrr)) == pytest.approx(10.0)
    assert float(np.nanmax(summary.chart_series[1].mrr)) == pytest.approx(40.0)


def test_chart_nan_gap_breaks_the_tool_line():
    count = 12
    positions = [coord for index in range(count) for coord in (float(index), 0.0, 0.0)]
    mrr = np.ones(count)
    mrr[4:8] = np.nan
    summary = summarize_file_sim(
        positions=positions,
        mrr=mrr,
        line_times=list(range(count)),
        vertex_types=_cut_types(count),
        tools=[4] * count,
    )

    series = summary.chart_series[0]
    assert series.label == "T4"
    assert np.isnan(series.mrr[4:8]).all()
    assert np.isfinite(series.mrr[3])
    assert np.isfinite(series.mrr[8])


def test_rapids_follow_their_tool_and_laser_stays_off_the_legend():
    summary = summarize_file_sim(
        positions=[0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0],
        mrr=np.array([0.0, 0.0, 12.0, 0.0]),
        line_times=[0.0, 1.0, 2.0, 3.0],
        vertex_types=[2.0, 2.0, 1.0, 1.0],
        tools=[2, 2, 2, 8888],
    )

    assert [series.label for series in summary.chart_series if series.label] == ["T2"]
    unlabeled = [series for series in summary.chart_series if series.label is None]
    assert len(unlabeled) == 1
    assert float(np.nanmax(unlabeled[0].mrr)) == 0.0


def test_chart_line_continues_through_a_retract():
    count = 6
    positions = [coord for index in range(count) for coord in (float(index), 0.0, 0.0)]
    summary = summarize_file_sim(
        positions=positions,
        mrr=np.array([0.0, 10.0, 10.0, 0.0, 10.0, 10.0]),
        line_times=list(range(count)),
        vertex_types=[1.0, 1.0, 1.0, 2.0, 1.0, 1.0],
        tools=[3] * count,
    )

    assert [series.label for series in summary.chart_series] == ["T3"]
    series = summary.chart_series[0]
    assert series.mrr.shape == (count,)
    assert np.isfinite(series.mrr).all()


def test_summary_exposes_vertex_times_in_chart_minutes():
    summary = summarize_file_sim(
        positions=[0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 20.0, 0.0, 0.0],
        mrr=np.array([0.0, 5.0, 5.0]),
        line_times=[0.0, 60.0, 120.0],
        vertex_types=_cut_types(3),
        tools=[1, 1, 1],
    )

    assert summary.vertex_times_min is not None
    assert summary.vertex_times_min.shape == (3,)
    assert summary.vertex_times_min[0] == 0.0
    assert summary.vertex_times_min[-1] == pytest.approx(summary.chart_series[0].times_min[-1])
    assert summarize_file_sim().vertex_times_min is None


def test_vertex_at_time_interpolates_and_clamps():
    times = np.array([0.0, 1.0, 1.0, 3.0])

    assert vertex_at_time(times, 0.5) == pytest.approx(0.5)
    assert vertex_at_time(times, 2.0) == pytest.approx(2.5)
    assert vertex_at_time(times, -4.0) == 0.0
    assert vertex_at_time(times, 99.0) == pytest.approx(3.0)
    assert vertex_at_time(None, 1.0) is None


def test_mrr_at_time_interpolates_and_skips_gaps():
    first = MrrChartSeries("T1", 1, np.array([0.0, 1.0, 3.0, 3.0, 4.0]), np.array([0.0, 10.0, 10.0, np.nan, 30.0]))
    second = MrrChartSeries("T2", 2, np.array([1.0, 3.0]), np.array([7.0, 7.0]))

    value, series = mrr_at_time([first, second], 0.5)
    assert value == pytest.approx(5.0)
    assert series.label == "T1"
    # T1 is interrupted after 3 min; T2 ended before.
    assert mrr_at_time([first, second], 3.5) is None
    assert mrr_at_time([first], 3.5) is None
    value, series = mrr_at_time([first, second], 4.0)
    assert value == pytest.approx(30.0)
    assert mrr_at_time([first, second], 9.0) is None


def _fake_viewer(lengths):
    moved = []
    viewer = SimpleNamespace(
        lengths=lengths,
        get_total_distance=lambda: lengths[-1] if lengths else 0.0,
        set_pos_by_distance=moved.append,
    )
    return viewer, moved


def test_seek_to_vertex_interpolates_and_clamps():
    viewer, moved = _fake_viewer([0.0, 10.0, 10.0, 30.0])

    assert GCodeViewer.seek_to_vertex(viewer, 0.5) is True
    assert GCodeViewer.seek_to_vertex(viewer, 2.5) is True
    assert GCodeViewer.seek_to_vertex(viewer, -3.0) is True
    assert GCodeViewer.seek_to_vertex(viewer, 99.0) is True
    assert moved == [pytest.approx(5.0), pytest.approx(20.0), 0.0, pytest.approx(30.0)]


def test_seek_to_vertex_without_a_toolpath_does_nothing():
    viewer, moved = _fake_viewer([])

    assert GCodeViewer.seek_to_vertex(viewer, 1.0) is False
    assert moved == []
