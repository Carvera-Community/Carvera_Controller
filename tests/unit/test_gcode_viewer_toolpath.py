"""Toolpath line-strip bridging keeps discrete attributes from interpolating."""

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.GcodeViewer import TOOL_PALETTE_SIZE, bridge_toolpath_vertices, toolpath_color_uniforms
from carveracontroller.ui.theme import Theme


def _pt(x, y, z, color, line_no, tool, feed=0.0, a=0.0, speed=0.0):
    return [float(x), float(y), float(z), float(a), float(color), float(line_no), int(tool), float(feed), float(speed)]


def _shader_tool_enabled(vertex_tool, filter_ids, tool_bits):
    """Python stand-in for toolpath.glsl is_tool_enabled (including fail-open)."""
    if not filter_ids:
        return True
    vtype = int(vertex_tool + 0.1)
    for i, tool_id in enumerate(filter_ids):
        if abs(vtype - int(tool_id)) < 0.5:
            return bool(tool_bits & (1 << i))
    return True


def _sample_interpolated_tools(a, b, steps=20):
    t0 = float(a[6])
    t1 = float(b[6])
    return [t0 + (t1 - t0) * (i / steps) for i in range(steps + 1)]


def _positive_length_pairs(rows):
    pairs = []
    for prev, cur in zip(rows, rows[1:]):
        dx = cur[0] - prev[0]
        dy = cur[1] - prev[1]
        dz = cur[2] - prev[2]
        if dx * dx + dy * dy + dz * dz > 1e-12:
            pairs.append((prev, cur))
    return pairs


def test_toolpath_color_uniforms_follow_the_theme():
    theme = Theme("monokai")
    values = toolpath_color_uniforms(theme)
    assert set(values) == {f"tool_color{index}" for index in range(TOOL_PALETTE_SIZE)} | {
        f"speed_color{index}" for index in range(4)
    }
    assert values["tool_color0"] == pytest.approx(list(theme.viewer_tool_color_1[:3]))
    assert values[f"tool_color{TOOL_PALETTE_SIZE - 1}"] == pytest.approx(list(theme.viewer_tool_color_10[:3]))
    assert values["speed_color0"] == pytest.approx(list(theme.speed_colormap_1[:3]))
    assert values["speed_color3"] == pytest.approx(list(theme.speed_colormap_4[:3]))


def test_color_change_still_duplicates_destination_with_previous_color():
    rows = [
        _pt(0, 0, 10, color=0, line_no=1, tool=1),
        _pt(0, 0, 0, color=1, line_no=2, tool=1),
    ]
    bridged = bridge_toolpath_vertices(rows)
    assert len(bridged) == 3
    assert bridged[1][0:3] == rows[1][0:3]
    assert bridged[1][4] == 0
    assert bridged[2][4] == 1


def test_tool_change_snap_attributes_connecting_move_to_new_tool():
    # Repro shape from "9 Top-Moto-Tag-01.cnc" around the T1 -> T6 change:
    # last T1 retract, then first T6 XY rapid (both G0).
    rows = [
        _pt(33.642, -8.04, 23.5, color=0, line_no=193, tool=1),
        _pt(130.258, 60.756, 23.5, color=0, line_no=206, tool=6),
    ]
    bridged = bridge_toolpath_vertices(rows)
    assert len(bridged) == 3
    snap = bridged[1]
    assert snap[0:3] == rows[0][0:3]
    assert snap[6] == 6
    assert bridged[2][6] == 6
    pairs = _positive_length_pairs(bridged)
    assert len(pairs) == 1
    assert pairs[0][0][6] == pairs[0][1][6] == 6


def test_tool_and_color_change_keep_each_segment_attribute_constant():
    rows = [
        _pt(0, 0, 0, color=1, line_no=1, tool=1, feed=300),
        _pt(10, 0, 10, color=0, line_no=2, tool=6),
    ]
    bridged = bridge_toolpath_vertices(rows)
    for prev, cur in zip(bridged, bridged[1:]):
        dx = cur[0] - prev[0]
        dy = cur[1] - prev[1]
        dz = cur[2] - prev[2]
        if dx * dx + dy * dy + dz * dz <= 1e-12:
            continue
        assert prev[6] == cur[6]
        assert prev[4] == cur[4]


def test_unchanged_attributes_are_not_duplicated():
    rows = [
        _pt(0, 0, 0, color=0, line_no=1, tool=1),
        _pt(1, 0, 0, color=0, line_no=2, tool=1),
    ]
    assert bridge_toolpath_vertices(rows) == rows


def test_chunk_boundary_uses_previous_vertex_for_tool_snap():
    prev = _pt(0, 0, 10, color=0, line_no=10, tool=1)
    nxt = [_pt(20, 5, 10, color=0, line_no=20, tool=6)]
    bridged = bridge_toolpath_vertices(nxt, prev_line=prev)
    assert bridged[0][0:3] == prev[0:3]
    assert bridged[0][6] == 6
    assert bridged[1] == nxt[0]


def test_hide_all_listed_tools_hides_tool_change_rapid():
    rows = [
        _pt(33.642, -8.04, 23.5, color=0, line_no=193, tool=1),
        _pt(130.258, 60.756, 23.5, color=0, line_no=206, tool=6),
    ]
    filter_ids = [1, 3, 6, 7]
    hidden_bits = 0

    leaked_before = []
    for prev, cur in _positive_length_pairs(rows):
        for sample in _sample_interpolated_tools(prev, cur):
            if _shader_tool_enabled(sample, filter_ids, hidden_bits):
                leaked_before.append(sample)
    assert leaked_before, "unbridged T1->T6 interpolation should fail-open"

    leaked_after = []
    for prev, cur in _positive_length_pairs(bridge_toolpath_vertices(rows)):
        for sample in _sample_interpolated_tools(prev, cur):
            if _shader_tool_enabled(sample, filter_ids, hidden_bits):
                leaked_after.append(sample)
    assert leaked_after == []


def test_parsed_tool_change_rapid_is_bridged():
    cnc = CNC()
    cnc.init()
    lines = [
        "G90 G21",
        "M6 T1",
        "G0 X33.642 Y-8.04 Z23.5",
        "M6 T6",
        "G0 X130.258 Y60.756",
    ]
    for i, line in enumerate(lines, 1):
        cnc.parseLine(line, i)

    bridged = bridge_toolpath_vertices(cnc.coordinates)
    for prev, cur in _positive_length_pairs(bridged):
        assert prev[6] == cur[6]
