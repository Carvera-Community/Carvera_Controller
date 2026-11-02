"""Kivy-free summary of a loaded toolpath and its baked material removal rate."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from carveracontroller.addons.stock.mrr_smoothing import MRR_SMOOTH_WINDOW_SEC, smooth_mrr_series

# Same number as CNC.LASER_TOOL_NUMBER. Kept here so this module does not import CNC.
DEFAULT_LASER_TOOL_NUMBER = 8888
CHART_BINS = 800
# Rapids and laser stay on the chart without a legend entry.
_UNLABELED_TOOL = -1


def _timing_constants():
    from carveracontroller.GcodeViewer import (
        DEFAULT_FEED_MM_MIN,
        MIN_FEED_MM_MIN,
        MOVE_EPS_MM,
        ROTARY_RADIUS_EPS_MM,
    )

    return DEFAULT_FEED_MM_MIN, MIN_FEED_MM_MIN, MOVE_EPS_MM, ROTARY_RADIUS_EPS_MM


@dataclass(frozen=True)
class MrrChartSeries:
    """One MRR line. ``label`` is None for rapids and laser."""

    label: str | None
    tool_number: int | None
    times_min: np.ndarray
    mrr: np.ndarray


@dataclass(frozen=True)
class FileSimSummary:
    filename: str
    has_path: bool
    estimated_sec: float | None
    path_length_mm: float | None
    removed_volume_mm3: float | None
    peak_mrr: float | None
    average_cutting_mrr: float | None
    bake_coverage: float | None
    chart_series: tuple[MrrChartSeries, ...]
    vertex_times_min: np.ndarray | None = None


def summarize_file_sim(
    *,
    filename: str = "",
    positions: Sequence[float] | None = None,
    mrr: np.ndarray | None = None,
    line_times: Sequence[float] | None = None,
    feeds: Sequence[float] | None = None,
    angles: Sequence[float] | None = None,
    axis_limits: Mapping[str, float] | None = None,
    vertex_types: Sequence[float] | None = None,
    tools: Sequence[float] | None = None,
    tool_table: Mapping | None = None,
    tool_unit_scale: float = 1.0,
    laser_tool_number: int = DEFAULT_LASER_TOOL_NUMBER,
    chart_bins: int = CHART_BINS,
    smooth_window_sec: float = MRR_SMOOTH_WINDOW_SEC,
) -> FileSimSummary:
    """File stats plus a downsampled programmed-time MRR series for the info popup.

    Removed volume, average and coverage come from the rate of each move as measured. The
    peak and the chart use rates averaged over the last ``smooth_window_sec`` seconds (0
    turns this off), so that very short moves do not make the readings jump around.
    """
    del tool_table, tool_unit_scale
    points = _positions(positions)
    if points is None:
        return _empty(filename)

    path_length = _path_length_mm(points)
    durations, cumulative, times_match = _segment_seconds(points, line_times, feeds, angles, axis_limits)
    estimated = float(line_times[-1]) if times_match and line_times is not None else None

    removed = None
    peak = None
    average = None
    coverage = None
    chart_series: tuple[MrrChartSeries, ...] = ()
    vertex_times_min: np.ndarray | None = None
    if mrr is not None:
        samples = np.array(mrr, dtype=np.float64, copy=True).reshape(-1)
        count = min(int(points.shape[0]), int(samples.shape[0]))
        if count > 0:
            samples = samples[:count]
            groups = _chart_groups(count, tools, laser_tool_number)
            smoothed = smooth_mrr_series(
                samples,
                durations[:count],
                _milling_mask(count, vertex_types, tools, laser_tool_number),
                smooth_window_sec,
                groups,
            )
            removed, peak, average, coverage = _mrr_stats(
                samples,
                durations[:count],
                vertex_types,
                tools,
                laser_tool_number,
                smoothed,
            )
            vertex_times_min = cumulative[:count] / 60.0
            chart_series = build_mrr_chart_series(vertex_times_min, smoothed, groups, chart_bins)

    return FileSimSummary(
        filename=filename or "",
        has_path=True,
        estimated_sec=estimated,
        path_length_mm=path_length,
        removed_volume_mm3=removed,
        peak_mrr=peak,
        average_cutting_mrr=average,
        bake_coverage=coverage,
        chart_series=chart_series,
        vertex_times_min=vertex_times_min,
    )


def mrr_at_time(series: Sequence[MrrChartSeries], time_min: float) -> tuple[float, MrrChartSeries] | None:
    """MRR drawn by the chart at ``time_min``, with the series it belongs to.

    Interpolates between the two neighbouring chart points of the series. Returns None where
    no series is drawn (before the start, after the end, or in a gap).
    """
    for item in series:
        times = item.times_min
        count = int(times.shape[0])
        if count == 0 or time_min < float(times[0]) or time_min > float(times[-1]):
            continue
        right = int(np.searchsorted(times, time_min, side="left"))
        if right >= count:
            right = count - 1
        left = max(right - 1, 0)
        low = float(item.mrr[left])
        high = float(item.mrr[right])
        if time_min >= float(times[right]) and math.isfinite(high):
            return high, item
        if not (math.isfinite(low) and math.isfinite(high)):
            continue
        span = float(times[right]) - float(times[left])
        if span <= 0.0:
            return high, item
        fraction = min(max((time_min - float(times[left])) / span, 0.0), 1.0)
        return low + (high - low) * fraction, item
    return None


def vertex_at_time(vertex_times_min: np.ndarray | None, time_min: float) -> float | None:
    """Fractional vertex index of the toolpath that is reached at ``time_min``."""
    if vertex_times_min is None:
        return None
    times = np.asarray(vertex_times_min, dtype=np.float64).reshape(-1)
    count = int(times.shape[0])
    if count == 0 or not math.isfinite(time_min):
        return None
    if count == 1:
        return 0.0
    clipped = min(max(time_min, float(times[0])), float(times[-1]))
    index = int(np.searchsorted(times, clipped, side="right")) - 1
    index = min(max(index, 0), count - 2)
    span = float(times[index + 1]) - float(times[index])
    fraction = (clipped - float(times[index])) / span if span > 0.0 else 0.0
    return float(index) + min(max(fraction, 0.0), 1.0)


def build_mrr_chart_series(
    times_min: np.ndarray,
    mrr: np.ndarray,
    groups: np.ndarray,
    bins: int = CHART_BINS,
) -> tuple[MrrChartSeries, ...]:
    """Downsample MRR per tool; unlabeled groups share one series."""
    times, values, grouped = _bin_mrr_runs(times_min, mrr, groups, bins)
    if times.size == 0:
        return ()
    seen: list[int] = []
    for group in grouped.tolist():
        number = int(group)
        if number not in seen:
            seen.append(number)
    draw = ([_UNLABELED_TOOL] if _UNLABELED_TOOL in seen else []) + [number for number in seen if number >= 0]
    series: list[MrrChartSeries] = []
    for group in draw:
        series_time, series_mrr = _series_with_gaps(times, values, grouped, group)
        if series_mrr.size == 0 or not np.isfinite(series_mrr).any():
            continue
        if group < 0:
            series.append(MrrChartSeries(None, None, series_time, series_mrr))
        else:
            series.append(MrrChartSeries(f"T{group}", group, series_time, series_mrr))
    return tuple(series)


def _bin_mrr_runs(
    times_min: np.ndarray,
    mrr: np.ndarray,
    groups: np.ndarray,
    bins: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    times = np.asarray(times_min, dtype=np.float64).reshape(-1)
    values = np.asarray(mrr, dtype=np.float64).reshape(-1)
    grouped = np.asarray(groups, dtype=np.int32).reshape(-1)
    if times.shape[0] != values.shape[0] or times.shape[0] != grouped.shape[0]:
        raise ValueError("times, mrr, and tool groups length mismatch")
    count = int(values.shape[0])
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty, np.empty(0, dtype=np.int32)
    bin_count = max(1, int(bins))
    if count <= bin_count:
        return times.copy(), values.copy(), grouped.copy()

    start = float(times[0])
    end = float(times[-1])
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        return _collapse_group_runs(times, values, grouped, start)

    edges = np.linspace(start, end, bin_count + 1)
    index = np.clip(np.searchsorted(edges, times, side="right") - 1, 0, bin_count - 1)
    out_time: list[float] = []
    out_value: list[float] = []
    out_group: list[int] = []
    cursor = 0
    while cursor < count:
        nxt = cursor + 1
        bin_id = int(index[cursor])
        group = int(grouped[cursor])
        while nxt < count and int(index[nxt]) == bin_id and int(grouped[nxt]) == group:
            nxt += 1
        chunk = values[cursor:nxt]
        finite = np.isfinite(chunk)
        value = float(chunk[finite].max()) if finite.any() else np.nan
        chunk_time = times[cursor:nxt]
        out_time.append(0.5 * (float(chunk_time.min()) + float(chunk_time.max())))
        out_value.append(value)
        out_group.append(group)
        cursor = nxt
    return (
        np.asarray(out_time, dtype=np.float64),
        np.asarray(out_value, dtype=np.float64),
        np.asarray(out_group, dtype=np.int32),
    )


def _collapse_group_runs(
    times: np.ndarray,
    values: np.ndarray,
    groups: np.ndarray,
    start: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origin = start if math.isfinite(start) else 0.0
    out_time: list[float] = []
    out_value: list[float] = []
    out_group: list[int] = []
    cursor = 0
    count = int(values.shape[0])
    while cursor < count:
        nxt = cursor + 1
        group = int(groups[cursor])
        while nxt < count and int(groups[nxt]) == group:
            nxt += 1
        chunk = values[cursor:nxt]
        finite = chunk[np.isfinite(chunk)]
        out_time.append(origin)
        out_value.append(float(finite.max()) if finite.size else np.nan)
        out_group.append(group)
        cursor = nxt
    return (
        np.asarray(out_time, dtype=np.float64),
        np.asarray(out_value, dtype=np.float64),
        np.asarray(out_group, dtype=np.int32),
    )


def _series_with_gaps(
    times: np.ndarray,
    values: np.ndarray,
    groups: np.ndarray,
    group: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Points for one tool, with a NaN wherever another tool interrupted it."""
    series_time: list[float] = []
    series_value: list[float] = []
    started = False
    gap = False
    for time_min, value, sample_group in zip(times, values, groups):
        if int(sample_group) != group:
            if started:
                gap = True
            continue
        if gap:
            series_time.append(float(time_min))
            series_value.append(np.nan)
            gap = False
        series_time.append(float(time_min))
        series_value.append(float(value) if math.isfinite(float(value)) else np.nan)
        started = True
    return np.asarray(series_time, dtype=np.float64), np.asarray(series_value, dtype=np.float64)


def _chart_groups(count: int, tools, laser_tool_number: int) -> np.ndarray:
    """Tool number per vertex. Rapids belong to the tool in effect; only the laser is unlabeled."""
    groups = np.full(count, _UNLABELED_TOOL, dtype=np.int32)
    if not tools:
        return groups
    limit = min(count, len(tools))
    for index in range(limit):
        try:
            number = int(tools[index])
        except (TypeError, ValueError):
            continue
        if number == int(laser_tool_number):
            continue
        groups[index] = number
    return groups


def _empty(filename: str) -> FileSimSummary:
    return FileSimSummary(
        filename=filename or "",
        has_path=False,
        estimated_sec=None,
        path_length_mm=None,
        removed_volume_mm3=None,
        peak_mrr=None,
        average_cutting_mrr=None,
        bake_coverage=None,
        chart_series=(),
    )


def _positions(positions: Sequence[float] | None) -> np.ndarray | None:
    if positions is None:
        return None
    flat = np.asarray(positions, dtype=np.float64).reshape(-1)
    usable = int(flat.shape[0] // 3)
    if usable <= 0:
        return None
    return flat[: usable * 3].reshape(usable, 3)


def _path_length_mm(points: np.ndarray) -> float:
    if points.shape[0] < 2:
        return 0.0
    delta = np.diff(points, axis=0)
    return float(np.sqrt((delta * delta).sum(axis=1)).sum())


def _segment_seconds(points, line_times, feeds, angles, limits):
    count = int(points.shape[0])
    durations = np.zeros(count, dtype=np.float64)
    cumulative = np.zeros(count, dtype=np.float64)
    times_match = line_times is not None and len(line_times) == count
    # With feeds, use the same timing the simulator divided its volumes by, so volume and
    # average MRR stay consistent with the stored rates. line_times is the fallback.
    if feeds is not None and len(feeds) > 0 and count >= 2:
        durations[1:] = _vector_segment_seconds(points, feeds, angles, limits)
        cumulative[1:] = np.cumsum(durations[1:])
        return durations, cumulative, times_match
    if times_match:
        cumulative[:] = np.asarray(line_times, dtype=np.float64)
        if count > 1:
            durations[1:] = np.diff(cumulative)
        np.maximum(durations, 0.0, out=durations)
        return durations, cumulative, True
    return durations, cumulative, False


def _vector_segment_seconds(points: np.ndarray, feeds, angles, limits) -> np.ndarray:
    """Programmed segment time (seconds), matching ``_segment_duration_sec``."""
    default_feed, min_feed, move_eps, rotary_eps = _timing_constants()
    delta = np.diff(points, axis=0)
    dx = np.abs(delta[:, 0])
    dy = np.abs(delta[:, 1])
    dz = np.abs(delta[:, 2])
    xyz = np.sqrt((delta * delta).sum(axis=1))
    feed = _float_values(feeds, int(points.shape[0]))[1:]
    rapid = feed < min_feed
    if angles is not None and len(angles) >= points.shape[0]:
        angle_values = _float_values(angles, int(points.shape[0]))
        da = np.abs(np.diff(angle_values))
    else:
        da = np.zeros(xyz.shape[0], dtype=np.float64)

    seek = _limit_value(limits, "seek", default_feed)
    if seek <= 0.0:
        seek = default_feed
    rapid_path = np.where(xyz > move_eps, xyz, da)
    duration_min = np.zeros(xyz.shape[0], dtype=np.float64)
    if seek > 0.0:
        duration_min[rapid] = rapid_path[rapid] / seek

    cutting = ~rapid
    if cutting.any():
        radius = np.hypot(points[1:, 1], points[1:, 2])
        perimeter = np.where(radius <= rotary_eps, 2.0 * math.pi, 2.0 * math.pi * radius)
        arc = perimeter * da / 360.0
        with_angle = cutting & (da > move_eps)
        straight = cutting & ~with_angle
        duration_min[with_angle] = np.maximum(xyz[with_angle], arc[with_angle]) / feed[with_angle]
        duration_min[straight] = xyz[straight] / feed[straight]

    if limits is not None:
        for component, key in ((dx, "x"), (dy, "y"), (dz, "z"), (da, "a")):
            axis_max = _limit_value(limits, key, 0.0)
            if axis_max > 0.0:
                limited = np.zeros(component.shape[0], dtype=np.float64)
                moving = component > 0.0
                limited[moving] = component[moving] / axis_max
                duration_min = np.maximum(duration_min, limited)
    return duration_min * 60.0


def _limit_value(limits, key: str, default: float) -> float:
    if not limits:
        return default
    try:
        return float(limits[key])
    except (KeyError, TypeError, ValueError):
        return default


def _float_values(values: Sequence[float] | None, count: int) -> np.ndarray:
    out = np.zeros(count, dtype=np.float64)
    if not values:
        return out
    limit = min(count, len(values))
    for index in range(limit):
        try:
            out[index] = float(values[index])
        except (TypeError, ValueError):
            out[index] = 0.0
    return out


def _mrr_stats(samples, durations, vertex_types, tools, laser_tool_number, peak_samples=None):
    finite = np.isfinite(samples)
    if not finite.any():
        removed = None
        peak = None
    else:
        removed = float((np.where(finite, samples, 0.0) * durations).sum() / 60.0)
        source = samples if peak_samples is None else peak_samples
        peak_finite = np.isfinite(source)
        peak = float(source[peak_finite].max()) if peak_finite.any() else None

    positive = finite & (samples > 0.0)
    if not positive.any():
        average = None
    else:
        weight = durations[positive]
        total = float(weight.sum())
        if total > 0.0:
            average = float((samples[positive] * weight).sum() / total)
        else:
            average = float(samples[positive].mean())

    milling = _milling_mask(int(samples.shape[0]), vertex_types, tools, laser_tool_number)
    if not milling.any():
        coverage = 1.0
    else:
        coverage = float(np.isfinite(samples[milling]).sum() / float(milling.sum()))
    return removed, peak, average, coverage


def _milling_mask(count: int, vertex_types, tools, laser_tool_number: int) -> np.ndarray:
    """Vertices the bake measures: cutting moves after the first, excluding laser."""
    mask = np.ones(count, dtype=bool)
    if count:
        mask[0] = False
    if vertex_types is not None and len(vertex_types) > 0:
        types = np.asarray(vertex_types, dtype=np.float64).reshape(-1)
        cutting = np.zeros(count, dtype=bool)
        limit = min(count, int(types.shape[0]))
        cutting[:limit] = types[:limit] <= 1.5
        mask &= cutting
    else:
        mask[:] = False
    if tools is not None and len(tools) > 0 and count:
        laser = np.zeros(count, dtype=bool)
        limit = min(count, len(tools))
        for index in range(limit):
            try:
                laser[index] = int(tools[index]) == int(laser_tool_number)
            except (TypeError, ValueError):
                laser[index] = False
        mask &= ~laser
    return mask
