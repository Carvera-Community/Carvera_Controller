"""Time estimates follow Carvera feed planning: XYZ, A surface speed, axis max (C1 defaults)."""

import math

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.GcodeViewer import (
    DEFAULT_AXIS_LIMITS,
    GCodeViewer,
    _a_surface_arc_mm,
    _axis_limits_from_app,
    _axis_limits_from_settings,
    _compute_line_times_worker,
    _segment_duration_sec,
)


def _times(raw_positions, feeds, angles=None, limits=None):
    n = len(feeds)
    linenumbers = list(range(n))
    return _compute_line_times_worker(raw_positions, linenumbers, feeds, None, 0, angles, limits)


def test_three_axis_length_over_feed():
    raw = [0.0, 0.0, 0.0, 100.0, 0.0, 0.0]
    times = _times(raw, [1000.0, 1000.0])
    assert times[-1] == 6.0


def test_three_axis_unchanged_when_a_is_constant():
    raw = [0.0, 0.0, 0.0, 100.0, 0.0, 0.0]
    times = _times(raw, [1000.0, 1000.0], angles=[0.0, 0.0])
    assert times[-1] == 6.0


def test_g1_a_only_uses_surface_speed():
    raw = [74.0, 0.0, 22.0, 74.0, 0.0, 22.0]
    times = _times(raw, [1500.0, 1500.0], angles=[0.0, -360.0])
    expected = (2.0 * math.pi * 22.0) / 1500.0 * 60.0
    assert times[-1] == pytest.approx(expected)


def test_a_only_without_angles_is_free():
    raw = [74.0, 0.0, 22.0, 74.0, 0.0, 22.0]
    times = _times(raw, [1500.0, 1500.0])
    assert times[-1] == 0.0


def test_wrapping_helix_uses_surface_not_xyz():
    start = (70.71, 0.0, 22.0)
    end = (69.32, 0.0, 22.0)
    raw = [*start, *end]
    times = _times(raw, [1500.0, 1500.0], angles=[-720.0, -1080.0])
    xyz_only = abs(end[0] - start[0]) / 1500.0 * 60.0
    arc = _a_surface_arc_mm(end, 360.0)
    expected = max(abs(end[0] - start[0]), arc) / 1500.0 * 60.0
    assert times[-1] == pytest.approx(expected)
    assert expected == pytest.approx(arc / 1500.0 * 60.0)
    assert xyz_only < 0.1
    assert expected > 5.0


def test_rapid_a_only_treats_degrees_as_mm():
    raw = [74.0, 0.0, 22.0, 74.0, 0.0, 22.0]
    times = _times(raw, [0.0, 0.0], angles=[0.0, -360.0])
    assert times[-1] == pytest.approx(7.2)


def test_rapid_a_only_clamps_to_a_max():
    raw = [74.0, 0.0, 22.0, 74.0, 0.0, 22.0]
    times = _times(raw, [0.0, 0.0], angles=[0.0, -360.0], limits=DEFAULT_AXIS_LIMITS)
    assert times[-1] == pytest.approx(12.0)


def test_g1_a_only_clamps_when_surface_exceeds_a_max():
    # r=22 mm at F1500 implies ~3900 deg/min, above C1's 1800 deg/min.
    raw = [74.0, 0.0, 22.0, 74.0, 0.0, 22.0]
    times = _times(raw, [1500.0, 1500.0], angles=[0.0, -360.0], limits=DEFAULT_AXIS_LIMITS)
    surface_sec = (2.0 * math.pi * 22.0) / 1500.0 * 60.0
    a_max_sec = 360.0 / 1800.0 * 60.0
    assert a_max_sec > surface_sec
    assert times[-1] == pytest.approx(a_max_sec)


def test_limits_none_does_not_clamp():
    raw = [0.0, 0.0, 100.0, 0.0, 0.0, 100.0]
    times = _times(raw, [3000.0, 3000.0], angles=[0.0, 360.0], limits=None)
    assert times[-1] == pytest.approx((2.0 * math.pi * 100.0) / 3000.0 * 60.0)


def test_axis_limits_from_settings_requires_all_max_rates():
    assert _axis_limits_from_settings(None) is None
    assert _axis_limits_from_settings({"alpha_max_rate": "3000"}) is None
    got = _axis_limits_from_settings(
        {
            "alpha_max_rate": "3000",
            "beta_max_rate": "3000",
            "gamma_max_rate": "2000",
            "delta_max_rate": "1800",
            "default_seek_rate": "2500",
        }
    )
    assert got == {"x": 3000.0, "y": 3000.0, "z": 2000.0, "a": 1800.0, "seek": 2500.0}


def test_axis_limits_from_app_reads_root_setting_list(monkeypatch):
    class Root:
        setting_list = {
            "alpha_max_rate": "3000",
            "beta_max_rate": "3000",
            "gamma_max_rate": "2000",
            "delta_max_rate": "1800",
        }

    class FakeApp:
        root = Root()

    monkeypatch.setattr("carveracontroller.GcodeViewer.App.get_running_app", lambda: FakeApp())
    got = _axis_limits_from_app()
    assert got["a"] == 1800.0
    assert got["seek"] == 3000.0


def test_axis_limits_from_app_falls_back_to_c1_defaults(monkeypatch):
    monkeypatch.setattr("carveracontroller.GcodeViewer.App.get_running_app", lambda: None)
    assert _axis_limits_from_app() == DEFAULT_AXIS_LIMITS


def test_axis_limits_from_app_falls_back_when_settings_incomplete(monkeypatch):
    class FakeApp:
        setting_list = {"alpha_max_rate": "3000"}
        root = None

    monkeypatch.setattr("carveracontroller.GcodeViewer.App.get_running_app", lambda: FakeApp())
    assert _axis_limits_from_app() == DEFAULT_AXIS_LIMITS


def test_rapid_xyz_plus_a_clamps_to_a_max():
    # Tiny X plus a full turn: without limits this is ~0.02s (XYZ/seek only).
    raw = [0.0, 0.0, 22.0, 1.0, 0.0, 22.0]
    unclamped = _times(raw, [0.0, 0.0], angles=[0.0, -360.0], limits=None)
    clamped = _times(raw, [0.0, 0.0], angles=[0.0, -360.0], limits=DEFAULT_AXIS_LIMITS)
    assert unclamped[-1] == pytest.approx(0.02)
    assert clamped[-1] == pytest.approx(12.0)


def test_parsed_a_only_g1_is_surface_time():
    cnc = CNC()
    lines = [
        "G90 G21",
        "G0 X74 Y0 Z22 A0",
        "G1 A-360 F1500",
    ]
    for i, line in enumerate(lines, 1):
        cnc.parseLine(line, i)

    raw = []
    angles = []
    feeds = []
    linenumbers = []
    for pt in cnc.coordinates:
        raw.extend([pt[0], pt[1], pt[2]])
        angles.append(pt[3])
        feeds.append(float(pt[7]) if pt[7] else 0.0)
        linenumbers.append(pt[5])

    times = _compute_line_times_worker(raw, linenumbers, feeds, None, 0, angles)
    assert times[-1] == pytest.approx((2.0 * math.pi * 22.0) / 1500.0 * 60.0, rel=1e-3)


def test_segment_duration_tiny_radius_uses_two_pi():
    # r = hypot(0, 0.05) ≤ 0.1 → perimeter 2π, not 2πr.
    sec = _segment_duration_sec((0.0, 0.0, 0.05), (0.0, 0.0, 0.05), 0.0, 360.0, 1500.0)
    assert sec == pytest.approx((2.0 * math.pi) / 1500.0 * 60.0)


def _bare_viewer(**kwargs):
    viewer = GCodeViewer.__new__(GCodeViewer)
    viewer.time_estimate_progress_callback = None
    viewer.legend_durations_cache = None
    viewer.line_times = []
    viewer.total_time = 0.0
    for key, value in kwargs.items():
        setattr(viewer, key, value)
    return viewer


def test_apply_line_times_reports_done_when_showing_progress():
    events = []
    viewer = _bare_viewer(time_estimate_progress_callback=lambda state, pct: events.append(state))
    viewer._apply_line_times_result([0.0, 6.0], show_progress=True)
    assert viewer.total_time == 6.0
    assert events == ["done"]


def test_apply_line_times_silent_reports_updated_not_done():
    events = []
    viewer = _bare_viewer(
        time_estimate_progress_callback=lambda state, pct: events.append(state),
        legend_durations_cache="stale",
    )
    viewer._apply_line_times_result([0.0, 6.0], show_progress=False)
    assert viewer.line_times == [0.0, 6.0]
    assert viewer.total_time == 6.0
    assert viewer.legend_durations_cache is None
    assert events == ["updated"]


def test_silent_async_keeps_existing_times_until_worker_starts(monkeypatch):
    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            pass

    monkeypatch.setattr("carveracontroller.GcodeViewer.threading.Thread", FakeThread)
    monkeypatch.setattr("carveracontroller.GcodeViewer._axis_limits_from_app", lambda: None)

    viewer = _bare_viewer(
        raw_linenumbers=[1, 2],
        raw_positions=[0.0, 0.0, 0.0, 100.0, 0.0, 0.0],
        raw_feed_rates=[1000.0, 1000.0],
        angles_of_vertices=[],
        line_times=[0.0, 5.0],
        total_time=5.0,
        legend_durations_cache="keep",
    )
    viewer._compute_line_times_async(show_progress=False)
    assert viewer.line_times == [0.0, 5.0]
    assert viewer.total_time == 5.0
    assert viewer.legend_durations_cache == "keep"


def test_progress_async_clears_times_when_starting(monkeypatch):
    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            pass

    monkeypatch.setattr("carveracontroller.GcodeViewer.threading.Thread", FakeThread)
    monkeypatch.setattr("carveracontroller.GcodeViewer._axis_limits_from_app", lambda: None)
    monkeypatch.setattr("carveracontroller.GcodeViewer.Clock.schedule_once", lambda *args, **kwargs: None)

    viewer = _bare_viewer(
        raw_linenumbers=[1, 2],
        raw_positions=[0.0, 0.0, 0.0, 100.0, 0.0, 0.0],
        raw_feed_rates=[1000.0, 1000.0],
        angles_of_vertices=[],
        line_times=[0.0, 5.0],
        total_time=5.0,
    )
    viewer._compute_line_times_async(show_progress=True)
    assert viewer.line_times == []
    assert viewer.total_time == 0.0
    assert viewer.line_times_job_show_progress is True


def test_stale_apply_is_ignored():
    events = []
    viewer = _bare_viewer(
        time_estimate_progress_callback=lambda state, pct: events.append(state),
        legend_durations_cache="keep",
        line_times=[0.0, 1.0],
        total_time=1.0,
    )
    viewer.line_times_job_id = 2
    viewer._apply_line_times_result([0.0, 99.0], show_progress=False, job_id=1)
    assert viewer.line_times == [0.0, 1.0]
    assert viewer.total_time == 1.0
    assert viewer.legend_durations_cache == "keep"
    assert events == []


def test_matching_job_id_applies():
    viewer = _bare_viewer()
    viewer.line_times_job_id = 2
    viewer._apply_line_times_result([0.0, 6.0], show_progress=False, job_id=2)
    assert viewer.total_time == 6.0
    assert viewer.line_times_job_show_progress is False


def test_stale_worker_does_not_overwrite_newer_times(monkeypatch):
    workers = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            workers.append(self)

        def start(self):
            pass

    scheduled = []
    monkeypatch.setattr("carveracontroller.GcodeViewer.threading.Thread", FakeThread)
    monkeypatch.setattr("carveracontroller.GcodeViewer.Clock.schedule_once", lambda cb, dt=0: scheduled.append(cb))
    monkeypatch.setattr("carveracontroller.GcodeViewer._axis_limits_from_app", lambda: None)

    viewer = _bare_viewer(
        raw_linenumbers=[1, 2],
        raw_positions=[0.0, 0.0, 0.0, 100.0, 0.0, 0.0],
        raw_feed_rates=[1000.0, 1000.0],
        angles_of_vertices=[],
        line_times=[],
        total_time=0.0,
    )
    viewer._compute_line_times_async(show_progress=False)

    viewer.raw_positions = [0.0, 0.0, 0.0, 50.0, 0.0, 0.0]
    viewer._compute_line_times_async(show_progress=False)

    workers[1].target()
    workers[0].target()
    for cb in scheduled:
        cb(0)

    assert viewer.total_time == 3.0


def test_silent_job_closes_progress_popup_of_superseded_job(monkeypatch):
    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target

        def start(self):
            pass

    monkeypatch.setattr("carveracontroller.GcodeViewer.threading.Thread", FakeThread)
    monkeypatch.setattr("carveracontroller.GcodeViewer._axis_limits_from_app", lambda: None)
    monkeypatch.setattr("carveracontroller.GcodeViewer.Clock.schedule_once", lambda *args, **kwargs: None)

    events = []
    viewer = _bare_viewer(
        raw_linenumbers=[1, 2],
        raw_positions=[0.0, 0.0, 0.0, 100.0, 0.0, 0.0],
        raw_feed_rates=[1000.0, 1000.0],
        angles_of_vertices=[],
        time_estimate_progress_callback=lambda state, pct: events.append(state),
    )
    viewer._compute_line_times_async(show_progress=True)
    assert viewer.line_times_job_show_progress is True
    viewer._compute_line_times_async(show_progress=False)
    assert events == ["done"]
    assert viewer.line_times_job_show_progress is False


def test_completed_progress_job_does_not_make_next_silent_send_done():
    events = []
    viewer = _bare_viewer(time_estimate_progress_callback=lambda state, pct: events.append(state))
    viewer.line_times_job_id = 1
    viewer.line_times_job_show_progress = True
    viewer._apply_line_times_result([0.0, 6.0], show_progress=True, job_id=1)
    assert events == ["done"]
    events.clear()
    viewer._begin_line_times_job(show_progress=False)
    assert events == []


def test_invalidate_without_closing_progress_does_not_send_done():
    events = []
    viewer = _bare_viewer(time_estimate_progress_callback=lambda state, pct: events.append(state))
    viewer.line_times_job_id = 1
    viewer.line_times_job_show_progress = True
    viewer._begin_line_times_job(show_progress=False, close_progress=False)
    assert events == []
    assert viewer.line_times_job_show_progress is False


def test_disable_drops_in_flight_result(monkeypatch):
    workers = []

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            self.target = target
            workers.append(self)

        def start(self):
            pass

    scheduled = []
    monkeypatch.setattr("carveracontroller.GcodeViewer.threading.Thread", FakeThread)
    monkeypatch.setattr("carveracontroller.GcodeViewer.Clock.schedule_once", lambda cb, dt=0: scheduled.append(cb))
    monkeypatch.setattr("carveracontroller.GcodeViewer._axis_limits_from_app", lambda: None)

    events = []
    viewer = _bare_viewer(
        raw_linenumbers=[1, 2],
        raw_positions=[0.0, 0.0, 0.0, 100.0, 0.0, 0.0],
        raw_feed_rates=[1000.0, 1000.0],
        angles_of_vertices=[],
        time_estimate_progress_callback=lambda state, pct: events.append(state),
    )
    viewer._compute_line_times_async(show_progress=True)

    viewer.line_times = []
    viewer.total_time = 0.0
    viewer._invalidate_legend_durations()
    viewer._begin_line_times_job(show_progress=False)

    workers[0].target()
    for cb in scheduled:
        cb(0)

    assert viewer.line_times == []
    assert viewer.total_time == 0.0
    assert "updated" not in events
    assert events.count("done") == 1
