"""Unit tests for facing toolpath generation (radius fillets and Archimedean spiral)."""

from __future__ import annotations

import math
import re

import pytest

from carveracontroller.addons.facing.facing_gcode import (
    MILLING_BOTH,
    MILLING_CLIMB,
    MILLING_CONVENTIONAL,
    PATTERN_RASTER_X,
    PATTERN_RASTER_Y,
    PATTERN_SPIRAL,
    PATTERN_SPIRAL_ROUND,
    FacingParams,
    _edge_mask,
    archimedean_spiral_polyline,
    compute_facing_envelope,
    facing_layer_xy_paths,
    facing_toolpath_xy_polyline,
    generate_facing_gcode,
    rect_spiral_polyline,
)
from carveracontroller.addons.facing.facing_path import Arc, Line, fillet_polyline, path_to_gcode
from carveracontroller.addons.facing.stock_geometry import STOCK_ORIGIN_CORNER_BL

_ARC_RE = re.compile(r"^(G2|G3) X(-?\d+\.\d+) Y(-?\d+\.\d+) I(-?\d+\.\d+) J(-?\d+\.\d+)")
_G1_RE = re.compile(r"^G1 X(-?\d+\.\d+) Y(-?\d+\.\d+)")
_ARC_LINE_RE = re.compile(r"^G[23]\s", re.MULTILINE)


def _has_xy_arc(gcode: str) -> bool:
    return _ARC_LINE_RE.search(gcode) is not None


def _params(**overrides) -> FacingParams:
    base = {
        "stock_width_mm": 40.0,
        "stock_length_mm": 20.0,
        "stock_origin_corner": STOCK_ORIGIN_CORNER_BL,
        "margin_x_mm": 0.0,
        "margin_y_mm": 0.0,
        "margin_z_mm": 0.0,
        "tool_diameter_mm": 2.0,
        "clearance_z_mm": 10.0,
        "spindle_rpm": 10000.0,
        "spindle_spinup_dwell_s": 0,
        "pattern": PATTERN_RASTER_X,
        "milling_direction": MILLING_BOTH,
        "rough_feed_mm_min": 1200.0,
        "rough_plunge_feed_mm_min": 400.0,
        "rough_stepover_mm": 2.0,
        "path_radius_mm": 0.0,
        "rough_depth_per_pass_mm": 1.0,
        "rough_total_depth_mm": 1.0,
        "finish_enabled": False,
        "finish_feed_mm_min": 600.0,
        "finish_stepover_mm": 0.5,
        "finish_depth_mm": 0.1,
        "ext_port_enabled": False,
        "ext_port_pwm": 100,
    }
    base.update(overrides)
    return FacingParams(**base)


def test_fillet_polyline_quarter_circle_ijk():
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    path = fillet_polyline(pts, 2.0)
    assert isinstance(path[0], Line)
    assert path[0].x1 == pytest.approx(8.0)
    assert path[0].y1 == pytest.approx(0.0)
    arc = path[1]
    assert isinstance(arc, Arc)
    assert arc.clockwise is False
    assert arc.x1 == pytest.approx(10.0)
    assert arc.y1 == pytest.approx(2.0)
    assert arc.cx == pytest.approx(8.0)
    assert arc.cy == pytest.approx(2.0)
    lines = path_to_gcode(path, 1000.0)
    assert any(s.startswith("G3 ") and "I0.0000 J2.0000" in s for s in lines)


def test_raster_both_radius_zero_is_g1_only():
    gcode = generate_facing_gcode(_params(path_radius_mm=0.0))
    assert not _has_xy_arc(gcode)
    assert "G1 X" in gcode
    assert "G17" in gcode


def test_raster_both_fillet_emits_g3_with_expected_ijk():
    # Envelope: tool 2mm, stock 40x20 → facing 1..39 x 1..19. Zigzag step 2.
    # First corner (39, 1): +X then +Y, G3 I0 J1 when R = step/2 = 1.
    gcode = generate_facing_gcode(_params(path_radius_mm=1.0))
    assert "G3 X39.0000 Y2.0000 I0.0000 J1.0000" in gcode
    assert "G3 X38.0000 Y3.0000 I-1.0000 J0.0000" in gcode


def test_raster_both_oversize_radius_clamped_to_half_stepover():
    gcode = generate_facing_gcode(_params(path_radius_mm=10.0, rough_stepover_mm=2.0))
    assert "G3 X39.0000 Y2.0000 I0.0000 J1.0000" in gcode


def test_climb_raster_retracts_and_ignores_radius():
    gcode = generate_facing_gcode(
        _params(
            milling_direction=MILLING_CLIMB,
            path_radius_mm=5.0,
        )
    )
    assert not _has_xy_arc(gcode)
    assert gcode.count("G0 Z10.0000") >= 3


def test_unknown_pattern_raises():
    with pytest.raises(ValueError, match="Unknown facing pattern"):
        compute_facing_envelope(_params(pattern="hexagon"))


def test_area_too_small_raises():
    with pytest.raises(ValueError, match="too small"):
        compute_facing_envelope(_params(stock_width_mm=1.0, stock_length_mm=1.0, tool_diameter_mm=10.0))


def test_spiral_both_still_rejected():
    with pytest.raises(ValueError, match="Climb or Conventional"):
        compute_facing_envelope(_params(pattern=PATTERN_SPIRAL, milling_direction=MILLING_BOTH))
    with pytest.raises(ValueError, match="Climb or Conventional"):
        compute_facing_envelope(_params(pattern=PATTERN_SPIRAL_ROUND, milling_direction=MILLING_BOTH))


def test_rect_spiral_radius_zero_is_g1_only():
    gcode = generate_facing_gcode(_params(pattern=PATTERN_SPIRAL, milling_direction=MILLING_CLIMB, path_radius_mm=0.0))
    assert not _has_xy_arc(gcode)
    assert "G1 X" in gcode


def test_rect_spiral_fillets_corners():
    gcode = generate_facing_gcode(
        _params(
            pattern=PATTERN_SPIRAL,
            milling_direction=MILLING_CLIMB,
            path_radius_mm=2.0,
        )
    )
    assert _has_xy_arc(gcode)
    # Outer loop climb: BL up to TL, then right — G2 quarter at TL, R=2.
    assert "G2 X3.0000 Y19.0000 I2.0000 J0.0000" in gcode


def test_rect_spiral_step_in_is_axis_aligned():
    env = compute_facing_envelope(_params(pattern=PATTERN_SPIRAL, milling_direction=MILLING_CLIMB))
    pts = rect_spiral_polyline(env, env.rough_stepover_mm)
    for a, b in zip(pts, pts[1:]):
        dx = abs(b[0] - a[0])
        dy = abs(b[1] - a[1])
        assert dx < 1e-6 or dy < 1e-6, f"diagonal step-in {a} -> {b}"


def _merged_intervals(
    pts: list[tuple[float, float]],
    *,
    x: float | None = None,
    y: float | None = None,
    eps: float = 1e-4,
) -> list[tuple[float, float]]:
    """Union of polyline spans that lie on a horizontal (y=) or vertical (x=) line."""
    raw: list[tuple[float, float]] = []
    for a, b in zip(pts, pts[1:]):
        if y is not None:
            if abs(a[1] - y) > eps or abs(b[1] - y) > eps:
                continue
            lo, hi = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
        else:
            assert x is not None
            if abs(a[0] - x) > eps or abs(b[0] - x) > eps:
                continue
            lo, hi = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
        if hi - lo > eps:
            raw.append((lo, hi))
    raw.sort()
    merged: list[tuple[float, float]] = []
    for lo, hi in raw:
        if not merged or lo > merged[-1][1] + eps:
            merged.append((lo, hi))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
    return merged


def test_rect_spiral_outer_loop_covers_envelope_edges():
    """Step-in must not skip a stepover of the outer stock-tangent envelope."""
    for mill in (MILLING_CLIMB, MILLING_CONVENTIONAL):
        env = compute_facing_envelope(_params(pattern=PATTERN_SPIRAL, milling_direction=mill))
        pts = rect_spiral_polyline(env, env.rough_stepover_mm)
        xa, xb = env.facing_xa, env.facing_xb
        ya, yb = env.facing_ya, env.facing_yb
        bottom = _merged_intervals(pts, y=ya)
        top = _merged_intervals(pts, y=yb)
        left = _merged_intervals(pts, x=xa)
        right = _merged_intervals(pts, x=xb)
        assert bottom == [pytest.approx((xa, xb), abs=1e-6)], f"{mill} bottom {bottom}"
        assert top == [pytest.approx((xa, xb), abs=1e-6)], f"{mill} top {top}"
        assert left == [pytest.approx((ya, yb), abs=1e-6)], f"{mill} left {left}"
        assert right == [pytest.approx((ya, yb), abs=1e-6)], f"{mill} right {right}"


def test_rect_spiral_step_in_keeps_fillet_sense():
    climb = generate_facing_gcode(_params(pattern=PATTERN_SPIRAL, milling_direction=MILLING_CLIMB, path_radius_mm=2.0))
    conv = generate_facing_gcode(
        _params(
            pattern=PATTERN_SPIRAL,
            milling_direction=MILLING_CONVENTIONAL,
            path_radius_mm=2.0,
        )
    )
    assert "G2 " in climb and "G3 " not in climb
    assert "G3 " in conv and "G2 " not in conv


def _on_envelope_edge(
    a: tuple[float, float],
    b: tuple[float, float],
    env,
    eps: float = 0.05,
) -> bool:
    xa, xb, ya, yb = env.facing_xa, env.facing_xb, env.facing_ya, env.facing_yb
    ax, ay = a
    bx, by = b
    same_x = abs(ax - bx) < eps
    same_y = abs(ay - by) < eps
    if same_x and (abs(ax - xa) < eps or abs(ax - xb) < eps):
        return min(ya, yb) - eps <= min(ay, by) and max(ay, by) <= max(ya, yb) + eps
    if same_y and (abs(ay - ya) < eps or abs(ay - yb) < eps):
        return min(xa, xb) - eps <= min(ax, bx) and max(ax, bx) <= max(xa, xb) + eps
    return False


def _dist_to_mask_edge(
    p: tuple[float, float],
    mask: int,
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> float:
    x, y = p
    d = math.inf
    if mask & 1:
        d = min(d, abs(y - ya))
    if mask & 2:
        d = min(d, abs(x - xb))
    if mask & 4:
        d = min(d, abs(y - yb))
    if mask & 8:
        d = min(d, abs(x - xa))
    return d


def test_spiral_visits_envelope_corners():
    p = _params(
        pattern=PATTERN_SPIRAL_ROUND,
        milling_direction=MILLING_CLIMB,
        margin_x_mm=5.0,
        margin_y_mm=3.0,
    )
    env = compute_facing_envelope(p)
    pts = archimedean_spiral_polyline(env, env.rough_stepover_mm)
    assert env.facing_xa < 0.0
    assert env.facing_ya < 0.0
    corners = (
        (env.facing_xa, env.facing_ya),
        (env.facing_xa, env.facing_yb),
        (env.facing_xb, env.facing_ya),
        (env.facing_xb, env.facing_yb),
    )
    for cx_, cy_ in corners:
        nearest = min(math.hypot(x - cx_, y - cy_) for x, y in pts)
        assert nearest < 0.05, f"spiral never nears corner {(cx_, cy_)}"
    cx = (env.facing_xa + env.facing_xb) * 0.5
    assert max(abs(x - cx) for x, y in pts) == pytest.approx((env.facing_xb - env.facing_xa) * 0.5, abs=0.05)


def test_spiral_flat_rectangle_inserts_skipped_edge_corners():
    """dtheta can jump a short side; sampler must still walk both corners, not a diagonal."""
    for mill in (MILLING_CLIMB, MILLING_CONVENTIONAL):
        p = _params(
            stock_width_mm=80.0,
            stock_length_mm=8.0,
            margin_x_mm=0.0,
            margin_y_mm=0.0,
            tool_diameter_mm=6.0,
            pattern=PATTERN_SPIRAL_ROUND,
            milling_direction=mill,
        )
        env = compute_facing_envelope(p)
        pts = archimedean_spiral_polyline(env, env.rough_stepover_mm)
        bl = (env.facing_xa, env.facing_ya)
        tl = (env.facing_xa, env.facing_yb)
        br = (env.facing_xb, env.facing_ya)
        tr = (env.facing_xb, env.facing_yb)
        for corner in (bl, tl, br, tr):
            nearest = min(math.hypot(x - corner[0], y - corner[1]) for x, y in pts)
            assert nearest < 0.05, f"{mill}: missed corner {corner}"
        assert pts[0] == pytest.approx(bl)
        dx = abs(pts[1][0] - pts[0][0])
        dy = abs(pts[1][1] - pts[0][1])
        assert dx < 1e-6 or dy < 1e-6, f"{mill}: first move is a diagonal shortcut"
        if mill == MILLING_CLIMB:
            assert dy > dx and pts[1][1] > pts[0][1]
        else:
            assert dx > dy and pts[1][0] > pts[0][0]


def test_spiral_stays_inside_envelope_and_ends_near_center():
    p = _params(pattern=PATTERN_SPIRAL_ROUND, milling_direction=MILLING_CLIMB)
    env = compute_facing_envelope(p)
    pts = archimedean_spiral_polyline(env, env.rough_stepover_mm)
    xa, xb, ya, yb = env.facing_xa, env.facing_xb, env.facing_ya, env.facing_yb
    for x, y in pts:
        assert xa - 1e-4 <= x <= xb + 1e-4
        assert ya - 1e-4 <= y <= yb + 1e-4
    cx = (xa + xb) * 0.5
    cy = (ya + yb) * 0.5
    assert math.hypot(pts[-1][0] - cx, pts[-1][1] - cy) < 1e-3
    r0 = math.hypot(pts[0][0] - cx, pts[0][1] - cy)
    r1 = math.hypot(pts[len(pts) // 2][0] - cx, pts[len(pts) // 2][1] - cy)
    assert r0 > r1


def test_round_spiral_has_no_crossing_shortcuts():
    """Long moves must follow the envelope; interior steps stay on the spiral."""
    p = _params(
        stock_width_mm=100.0,
        stock_length_mm=80.0,
        margin_x_mm=6.0,
        margin_y_mm=6.0,
        tool_diameter_mm=6.0,
        pattern=PATTERN_SPIRAL_ROUND,
        milling_direction=MILLING_CLIMB,
        rough_stepover_mm=2.0,
    )
    env = compute_facing_envelope(p)
    pts = archimedean_spiral_polyline(env, env.rough_stepover_mm)
    step = env.rough_stepover_mm
    for a, b in zip(pts, pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d <= step * 4.0:
            continue
        assert _on_envelope_edge(a, b, env), f"shortcut {a} -> {b} ({d:.1f} mm)"


def test_round_spiral_leaves_edges_at_circle_intersection():
    """Leaving a wall onto the spiral must happen near that wall, not as a corner chamfer."""
    p = _params(
        stock_width_mm=100.0,
        stock_length_mm=80.0,
        margin_x_mm=6.0,
        margin_y_mm=6.0,
        tool_diameter_mm=6.0,
        pattern=PATTERN_SPIRAL_ROUND,
        milling_direction=MILLING_CLIMB,
        rough_stepover_mm=2.0,
    )
    env = compute_facing_envelope(p)
    xa, xb, ya, yb = env.facing_xa, env.facing_xb, env.facing_ya, env.facing_yb
    pts = archimedean_spiral_polyline(env, env.rough_stepover_mm)
    for a, b in zip(pts, pts[1:]):
        ma = _edge_mask(a, xa, xb, ya, yb)
        mb = _edge_mask(b, xa, xb, ya, yb)
        if ma in (1, 2, 4, 8) and mb == 0:
            dist_to_wall = _dist_to_mask_edge(b, ma, xa, xb, ya, yb)
            assert dist_to_wall < 1.25, f"chamfer {a} -> {b} (dist {dist_to_wall:.2f})"


def test_spiral_is_not_nested_rectangles():
    p = _params(pattern=PATTERN_SPIRAL_ROUND, milling_direction=MILLING_CLIMB)
    gcode = generate_facing_gcode(p)
    both_xy = []
    for line in gcode.splitlines():
        m = _G1_RE.match(line)
        if not m:
            continue
        x, y = float(m.group(1)), float(m.group(2))
        both_xy.append((x, y))
    diagonalish = 0
    prev = None
    for x, y in both_xy:
        if prev is not None:
            dx = abs(x - prev[0])
            dy = abs(y - prev[1])
            if dx > 1e-4 and dy > 1e-4:
                diagonalish += 1
        prev = (x, y)
    assert diagonalish >= 8


def test_spiral_climb_goes_up_left_conventional_along_bottom():
    climb = _params(pattern=PATTERN_SPIRAL_ROUND, milling_direction=MILLING_CLIMB)
    conv = _params(pattern=PATTERN_SPIRAL_ROUND, milling_direction=MILLING_CONVENTIONAL)
    env_c = compute_facing_envelope(climb)
    env_v = compute_facing_envelope(conv)
    pc = archimedean_spiral_polyline(env_c, env_c.rough_stepover_mm)
    pv = archimedean_spiral_polyline(env_v, env_v.rough_stepover_mm)
    assert abs(pc[1][0] - pc[0][0]) < abs(pc[1][1] - pc[0][1])
    assert pc[1][1] > pc[0][1]
    assert abs(pv[1][1] - pv[0][1]) < abs(pv[1][0] - pv[0][0])
    assert pv[1][0] > pv[0][0]


def test_spiral_with_radius_emits_fillet_arcs():
    gcode = generate_facing_gcode(
        _params(
            pattern=PATTERN_SPIRAL_ROUND,
            milling_direction=MILLING_CLIMB,
            path_radius_mm=2.0,
        )
    )
    assert _has_xy_arc(gcode)
    for line in gcode.splitlines():
        m = _ARC_RE.match(line)
        if m:
            i_off, j_off = float(m.group(4)), float(m.group(5))
            assert math.hypot(i_off, j_off) == pytest.approx(2.0, abs=0.05)
            break
    else:
        pytest.fail("expected a G2/G3 fillet in spiral output")


def test_negative_path_radius_clamped():
    env = compute_facing_envelope(_params(path_radius_mm=-3.0))
    assert env.path_radius_mm == 0.0


def test_along_y_zigzag_fillets():
    gcode = generate_facing_gcode(_params(pattern=PATTERN_RASTER_Y, path_radius_mm=1.0))
    assert _has_xy_arc(gcode)


def test_facing_layer_paths_preview_matches_gcode_start():
    p = _params(path_radius_mm=1.0)
    env = compute_facing_envelope(p)
    paths = facing_layer_xy_paths(env, env.rough_stepover_mm)
    assert paths and isinstance(paths[0][0], Line)
    preview = facing_toolpath_xy_polyline(env)
    assert preview[0] == pytest.approx((paths[0][0].x0, paths[0][0].y0))


def test_preview_decimate_does_not_skip_rectangle_corners():
    """Index striding joins opposite corners of a collapsed outer loop."""
    from carveracontroller.addons.facing.facing_preview_sketch import (
        decimate_preview_polyline,
    )

    rect = [
        (-10.0, -1.0),
        (-10.0, 101.0),
        (110.0, 101.0),
        (110.0, -1.0),
        (-10.0, -1.0),
    ]
    dense = [(float(i) * 0.05, 50.0) for i in range(2500)]
    pts = rect + dense
    step = max(1, len(pts) // 400)
    strided = [pts[i] for i in range(0, len(pts), step)]
    sdx = abs(strided[1][0] - strided[0][0])
    sdy = abs(strided[1][1] - strided[0][1])
    assert sdx > 1e-6 and sdy > 1e-6

    out = decimate_preview_polyline(pts, max_points=400)
    dx = abs(out[1][0] - out[0][0])
    dy = abs(out[1][1] - out[0][1])
    assert dx < 1e-6 or dy < 1e-6, f"preview skipped a rectangle edge: {out[0]} -> {out[1]}"


def test_round_spiral_preview_decimate_has_no_crossing_shortcuts():
    from carveracontroller.addons.facing.facing_preview_sketch import (
        decimate_preview_polyline,
    )

    p = _params(
        stock_width_mm=100.0,
        stock_length_mm=100.0,
        margin_x_mm=10.0,
        margin_y_mm=1.0,
        tool_diameter_mm=6.0,
        pattern=PATTERN_SPIRAL_ROUND,
        milling_direction=MILLING_CLIMB,
        rough_stepover_mm=2.0,
    )
    env = compute_facing_envelope(p)
    pts = facing_toolpath_xy_polyline(env)
    preview = decimate_preview_polyline(pts, max_points=400)
    dx0 = abs(preview[1][0] - preview[0][0])
    dy0 = abs(preview[1][1] - preview[0][1])
    assert dx0 < 1e-6 or dy0 < 1e-6, f"preview first move is a diagonal: {preview[0]} -> {preview[1]}"
    span = min(env.facing_xb - env.facing_xa, env.facing_yb - env.facing_ya)
    for a, b in zip(preview, preview[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d <= span * 0.35:
            continue
        assert _on_envelope_edge(a, b, env), f"preview shortcut {a} -> {b} ({d:.1f} mm)"
