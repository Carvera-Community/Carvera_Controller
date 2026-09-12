"""
Facing toolpath generator

Set WCS XY origin at the stock corner chosen on the wizard; width follows + or - X,
length follows + or - Y from that corner. Z0 at the top surface; cuts use negative Z.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from carveracontroller.translation import tr

from .facing_path import (
    PathElement,
    fillet_polyline,
    path_to_gcode,
    path_to_preview_xy,
)
from .stock_geometry import (
    STOCK_ORIGIN_CORNER_BL,
    STOCK_ORIGIN_CORNER_BR,
    STOCK_ORIGIN_CORNER_CEN,
    STOCK_ORIGIN_CORNER_TL,
    STOCK_ORIGIN_CORNER_TR,
    stock_rect_from_origin_corner,
)

MILLING_CLIMB = "climb"
MILLING_CONVENTIONAL = "conventional"
MILLING_BOTH = "both"

PATTERN_RASTER_X = "raster_x"
PATTERN_RASTER_Y = "raster_y"
PATTERN_SPIRAL = "spiral"
PATTERN_SPIRAL_ROUND = "spiral_round"

_SPIRAL_PATTERNS = (PATTERN_SPIRAL, PATTERN_SPIRAL_ROUND)

_SPIRAL_CHORD_ERR_MM = 0.05
_SPIRAL_MAX_DTHETA = math.pi / 8.0
_SPIRAL_MIN_DTHETA = 1e-4
_SPIRAL_MAX_POINTS = 50000
_SPIRAL_CLIP_SEG_MM = 1.0
_SPIRAL_CLIP_SUBDIV = 12
_EDGE_EPS = 1e-4
_EDGE_BOTTOM = 1
_EDGE_RIGHT = 2
_EDGE_TOP = 4
_EDGE_LEFT = 8
_EDGE_SINGLE = (_EDGE_BOTTOM, _EDGE_RIGHT, _EDGE_TOP, _EDGE_LEFT)
_WINDING_CLIMB = (_EDGE_LEFT, _EDGE_TOP, _EDGE_RIGHT, _EDGE_BOTTOM)
_WINDING_CONVENTIONAL = (_EDGE_BOTTOM, _EDGE_RIGHT, _EDGE_TOP, _EDGE_LEFT)


@dataclass
class FacingParams:
    stock_width_mm: float
    stock_length_mm: float
    stock_origin_corner: str
    margin_x_mm: float
    margin_y_mm: float
    margin_z_mm: float
    tool_diameter_mm: float
    clearance_z_mm: float
    spindle_rpm: float
    spindle_spinup_dwell_s: int
    pattern: str
    milling_direction: str
    rough_feed_mm_min: float
    rough_plunge_feed_mm_min: float
    rough_stepover_mm: float
    path_radius_mm: float
    rough_depth_per_pass_mm: float
    rough_total_depth_mm: float
    finish_enabled: bool
    finish_feed_mm_min: float
    finish_stepover_mm: float
    finish_depth_mm: float
    ext_port_enabled: bool
    ext_port_pwm: int


@dataclass(frozen=True)
class FacingEnvelope:
    """Stock+margins rectangle and inset facing rectangle (mm, work coordinates)."""

    origin_corner: str
    stock_x0: float
    stock_x1: float
    stock_y0: float
    stock_y1: float
    facing_xa: float
    facing_xb: float
    facing_ya: float
    facing_yb: float
    rough_stepover_mm: float
    path_radius_mm: float
    pattern: str
    milling_direction: str


def _inset_span(p0: float, p1: float, r: float) -> tuple[float, float]:
    return p0 + r, p1 - r


def compute_facing_envelope(p: FacingParams) -> FacingEnvelope:
    w = p.stock_width_mm
    sl = p.stock_length_mm
    mx = p.margin_x_mm
    my = p.margin_y_mm
    rad = p.tool_diameter_mm / 2.0

    pattern = p.pattern.strip().lower()
    if pattern not in (PATTERN_RASTER_X, PATTERN_RASTER_Y, PATTERN_SPIRAL, PATTERN_SPIRAL_ROUND):
        raise ValueError(tr._("Unknown facing pattern."))
    if pattern in _SPIRAL_PATTERNS and p.milling_direction == MILLING_BOTH:
        raise ValueError(tr._("Spiral facing requires Climb or Conventional milling, not Both."))

    nx0, ny0, nx1, ny1 = stock_rect_from_origin_corner(w, sl, p.stock_origin_corner)
    x0 = nx0 - mx
    x1 = nx1 + mx
    y0 = ny0 - my
    y1 = ny1 + my

    xa, xb = _inset_span(x0, x1, rad)
    ya, yb = _inset_span(y0, y1, rad)
    if xa >= xb - 1e-6 or ya >= yb - 1e-6:
        raise ValueError(tr._("Facing area too small for tool diameter (after margins and radius)."))

    total_cut = p.rough_total_depth_mm + p.margin_z_mm
    if total_cut <= 0:
        raise ValueError(tr._("Total facing depth must be positive."))

    rough_step = max(p.rough_stepover_mm, 0.05)
    return FacingEnvelope(
        origin_corner=p.stock_origin_corner.strip().lower(),
        stock_x0=x0,
        stock_x1=x1,
        stock_y0=y0,
        stock_y1=y1,
        facing_xa=xa,
        facing_xb=xb,
        facing_ya=ya,
        facing_yb=yb,
        rough_stepover_mm=rough_step,
        path_radius_mm=max(0.0, p.path_radius_mm),
        pattern=pattern,
        milling_direction=p.milling_direction,
    )


def _rough_z_levels(p: FacingParams) -> list[float]:
    total_cut = p.rough_total_depth_mm + p.margin_z_mm
    doc = max(p.rough_depth_per_pass_mm, 0.01)
    z_levels: list[float] = []
    z = -doc
    while z > -total_cut + 1e-6:
        z_levels.append(z)
        z -= doc
    z_levels.append(-total_cut)
    return z_levels


def compute_facing_z_levels(p: FacingParams) -> list[float]:
    """Rough Z cutting depths (negative), including final level at -total_cut."""
    compute_facing_envelope(p)
    return _rough_z_levels(p)


def _rows_along_x(corner: str, ya: float, yb: float, step: float) -> list[float]:
    if corner in (STOCK_ORIGIN_CORNER_BL, STOCK_ORIGIN_CORNER_BR, STOCK_ORIGIN_CORNER_CEN):
        ys: list[float] = []
        y = ya
        while y <= yb + 1e-6:
            ys.append(y)
            y += step
        return ys
    ys = []
    y = yb
    while y >= ya - 1e-6:
        ys.append(y)
        y -= step
    return ys


def _cols_along_y(corner: str, xa: float, xb: float, step: float) -> list[float]:
    if corner in (STOCK_ORIGIN_CORNER_BL, STOCK_ORIGIN_CORNER_TL, STOCK_ORIGIN_CORNER_CEN):
        xs: list[float] = []
        x = xa
        while x <= xb + 1e-6:
            xs.append(x)
            x += step
        return xs
    xs = []
    x = xb
    while x >= xa - 1e-6:
        xs.append(x)
        x -= step
    return xs


def _climb_is_forward(corner: str, raster_along_x: bool) -> bool:
    """Whether forward (xa->xb / ya->yb = increasing coordinate) is the climb direction

    Raster along X, stepover +Y (bl/br): climb = -X  -> forward=False
    Raster along X, stepover -Y (tl/tr): climb = +X  -> forward=True
    Raster along Y, stepover +X (bl/tl): climb = +Y  -> forward=True
    Raster along Y, stepover -X (br/tr): climb = -Y  -> forward=False
    """

    if raster_along_x:
        return corner in (STOCK_ORIGIN_CORNER_TL, STOCK_ORIGIN_CORNER_TR)
    return corner in (STOCK_ORIGIN_CORNER_BL, STOCK_ORIGIN_CORNER_TL, STOCK_ORIGIN_CORNER_CEN)


def iter_raster_passes(
    env: FacingEnvelope,
    step_mm: float,
) -> Iterator[tuple[tuple[float, float], tuple[float, float]]]:
    xa, xb = env.facing_xa, env.facing_xb
    ya, yb = env.facing_ya, env.facing_yb
    step = max(step_mm, 0.05)
    c = env.origin_corner
    md = env.milling_direction
    along_x = env.pattern == PATTERN_RASTER_X

    climb_fwd = _climb_is_forward(c, along_x)
    if md == MILLING_CLIMB:
        fixed_forward = climb_fwd
    elif md == MILLING_CONVENTIONAL:
        fixed_forward = not climb_fwd
    else:
        fixed_forward = None

    if along_x:
        forward = (
            fixed_forward
            if fixed_forward is not None
            else c in (STOCK_ORIGIN_CORNER_BL, STOCK_ORIGIN_CORNER_TL, STOCK_ORIGIN_CORNER_CEN)
        )
        for y in _rows_along_x(c, ya, yb, step):
            xs = xa if forward else xb
            xe = xb if forward else xa
            yield (xs, y), (xe, y)
            if fixed_forward is None:
                forward = not forward
    else:
        forward = (
            fixed_forward
            if fixed_forward is not None
            else c in (STOCK_ORIGIN_CORNER_BL, STOCK_ORIGIN_CORNER_BR, STOCK_ORIGIN_CORNER_CEN)
        )
        for x in _cols_along_y(c, xa, xb, step):
            ys = ya if forward else yb
            ye = yb if forward else ya
            yield (x, ys), (x, ye)
            if fixed_forward is None:
                forward = not forward


def _connected_raster_polyline(
    env: FacingEnvelope,
    step_mm: float,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for (sx, sy), (ex, ey) in iter_raster_passes(env, step_mm):
        if not pts or math.hypot(sx - pts[-1][0], sy - pts[-1][1]) > 1e-7:
            pts.append((sx, sy))
        pts.append((ex, ey))
    return pts


def iter_spiral_rect_passes(
    env: FacingEnvelope,
    step_mm: float,
) -> Iterator[tuple[tuple[float, float], tuple[float, float]]]:
    """Nested rectangles outside -> inwards.
    When another loop remains, the last side stops at the next loop's inset
    and steps in axis-aligned. Filleting that 90° is a single arc.
    """
    xa, xb = env.facing_xa, env.facing_xb
    ya, yb = env.facing_ya, env.facing_yb
    step = max(step_mm, 0.05)
    ccw = env.milling_direction == MILLING_CLIMB

    k = 0
    while True:
        L = xa + k * step
        R = xb - k * step
        B = ya + k * step
        T = yb - k * step
        if R - L < 1e-6 or T - B < 1e-6:
            break

        L2 = xa + (k + 1) * step
        R2 = xb - (k + 1) * step
        B2 = ya + (k + 1) * step
        T2 = yb - (k + 1) * step
        has_next = R2 - L2 >= 1e-6 and T2 - B2 >= 1e-6

        if ccw:
            if has_next:
                segments = (
                    ((L, B), (L, T)),
                    ((L, T), (R, T)),
                    ((R, T), (R, B)),
                    ((R, B), (L2, B)),
                )
                # Cover the envelope stub the step-in would skip (bottom, BL).
                if k == 0:
                    segments = (((L2, B), (L, B)),) + segments
            else:
                segments = (
                    ((L, B), (L, T)),
                    ((L, T), (R, T)),
                    ((R, T), (R, B)),
                    ((R, B), (L, B)),
                )
        else:
            if has_next:
                segments = (
                    ((L, B), (R, B)),
                    ((R, B), (R, T)),
                    ((R, T), (L, T)),
                    ((L, T), (L, B2)),
                    ((L, B2), (L2, B2)),
                )
                # Cover the envelope stub the step-in would skip (left, BL).
                if k == 0:
                    segments = (((L, B2), (L, B)),) + segments
            else:
                segments = (
                    ((L, B), (R, B)),
                    ((R, B), (R, T)),
                    ((R, T), (L, T)),
                    ((L, T), (L, B)),
                )
        yield from segments
        if not has_next:
            break
        k += 1


def rect_spiral_polyline(
    env: FacingEnvelope,
    step_mm: float,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for (sx, sy), (ex, ey) in iter_spiral_rect_passes(env, step_mm):
        if not pts or math.hypot(sx - pts[-1][0], sy - pts[-1][1]) > 1e-7:
            pts.append((sx, sy))
        pts.append((ex, ey))
    return pts


def _dtheta_for_radius(r: float) -> float:
    r_eff = max(r, _SPIRAL_CHORD_ERR_MM)
    dt = math.sqrt(8.0 * _SPIRAL_CHORD_ERR_MM / r_eff)
    return min(_SPIRAL_MAX_DTHETA, max(_SPIRAL_MIN_DTHETA, dt))


def _ray_rect_boundary(
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> tuple[float, float]:
    """First hit of a ray from the rect center with the rectangle boundary."""
    t_hit = math.inf
    eps = 1e-15
    if dx > eps:
        t_hit = min(t_hit, (xb - cx) / dx)
    elif dx < -eps:
        t_hit = min(t_hit, (xa - cx) / dx)
    if dy > eps:
        t_hit = min(t_hit, (yb - cy) / dy)
    elif dy < -eps:
        t_hit = min(t_hit, (ya - cy) / dy)
    if not math.isfinite(t_hit) or t_hit <= 0.0:
        return cx, cy
    return cx + t_hit * dx, cy + t_hit * dy


def _clip_polar_to_rect(
    cx: float,
    cy: float,
    r: float,
    theta: float,
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> tuple[float, float]:
    dx = math.cos(theta)
    dy = math.sin(theta)
    px = cx + r * dx
    py = cy + r * dy
    if xa - 1e-9 <= px <= xb + 1e-9 and ya - 1e-9 <= py <= yb + 1e-9:
        return (
            min(max(px, xa), xb),
            min(max(py, ya), yb),
        )
    hx, hy = _ray_rect_boundary(cx, cy, dx, dy, xa, xb, ya, yb)
    return (
        min(max(hx, xa), xb),
        min(max(hy, ya), yb),
    )


def _edge_mask(
    p: tuple[float, float],
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> int:
    x, y = p
    m = 0
    if abs(y - ya) <= _EDGE_EPS and xa - _EDGE_EPS <= x <= xb + _EDGE_EPS:
        m |= _EDGE_BOTTOM
    if abs(x - xb) <= _EDGE_EPS and ya - _EDGE_EPS <= y <= yb + _EDGE_EPS:
        m |= _EDGE_RIGHT
    if abs(y - yb) <= _EDGE_EPS and xa - _EDGE_EPS <= x <= xb + _EDGE_EPS:
        m |= _EDGE_TOP
    if abs(x - xa) <= _EDGE_EPS and ya - _EDGE_EPS <= y <= yb + _EDGE_EPS:
        m |= _EDGE_LEFT
    return m


def _rect_corner_for_edges(
    edge_a: int,
    edge_b: int,
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> tuple[float, float] | None:
    mask = edge_a | edge_b
    if mask == (_EDGE_BOTTOM | _EDGE_LEFT):
        return xa, ya
    if mask == (_EDGE_LEFT | _EDGE_TOP):
        return xa, yb
    if mask == (_EDGE_TOP | _EDGE_RIGHT):
        return xb, yb
    if mask == (_EDGE_RIGHT | _EDGE_BOTTOM):
        return xb, ya
    return None


def _outgoing_edge(mask: int, winding: tuple[int, ...]) -> int | None:
    if mask in _EDGE_SINGLE:
        return mask
    for i, edge in enumerate(winding):
        nxt = winding[(i + 1) % 4]
        if (mask & edge) and (mask & nxt):
            return nxt
    return None


def _append_unique(pts: list[tuple[float, float]], q: tuple[float, float]) -> None:
    if not pts or math.hypot(pts[-1][0] - q[0], pts[-1][1] - q[1]) > 1e-7:
        pts.append(q)


def _insert_skipped_edge_corners(
    pts: list[tuple[float, float]],
    last_m: int,
    p_m: int,
    winding: tuple[int, ...],
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> None:
    """Walk winding from last to p, inserting both corners of any skipped edge."""
    start = _outgoing_edge(last_m, winding)
    if start is None or (p_m & start):
        return
    edge = start
    for _ in range(4):
        if p_m & edge:
            return
        nxt = winding[(winding.index(edge) + 1) % 4]
        corner = _rect_corner_for_edges(edge, nxt, xa, xb, ya, yb)
        if corner is None:
            return
        _append_unique(pts, corner)
        edge = nxt


def _append_spiral_point(
    pts: list[tuple[float, float]],
    p: tuple[float, float],
    xa: float,
    xb: float,
    ya: float,
    yb: float,
    winding: tuple[int, ...],
) -> None:
    if not pts:
        pts.append(p)
        return
    last_m = _edge_mask(pts[-1], xa, xb, ya, yb)
    p_m = _edge_mask(p, xa, xb, ya, yb)
    if last_m and p_m:
        _insert_skipped_edge_corners(pts, last_m, p_m, winding, xa, xb, ya, yb)
    _append_unique(pts, p)


def _clip_span_needs_subdivide(
    p0: tuple[float, float],
    p1: tuple[float, float],
    xa: float,
    xb: float,
    ya: float,
    yb: float,
) -> bool:
    """True when a straight clip-to-clip chord would chamfer a corner."""
    d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if d <= _SPIRAL_CLIP_SEG_MM:
        return False
    m0 = _edge_mask(p0, xa, xb, ya, yb)
    m1 = _edge_mask(p1, xa, xb, ya, yb)
    if m0 == 0 and m1 == 0:
        return False
    return m0 & m1 not in _EDGE_SINGLE


def _emit_clipped_span(
    pts: list[tuple[float, float]],
    cx: float,
    cy: float,
    r0: float,
    t0: float,
    r1: float,
    t1: float,
    xa: float,
    xb: float,
    ya: float,
    yb: float,
    winding: tuple[int, ...],
    depth: int = 0,
) -> None:
    p1 = _clip_polar_to_rect(cx, cy, r1, t1, xa, xb, ya, yb)
    p0 = pts[-1] if pts else _clip_polar_to_rect(cx, cy, r0, t0, xa, xb, ya, yb)
    if depth < _SPIRAL_CLIP_SUBDIV and _clip_span_needs_subdivide(p0, p1, xa, xb, ya, yb):
        tm = 0.5 * (t0 + t1)
        rm = 0.5 * (r0 + r1)
        _emit_clipped_span(pts, cx, cy, r0, t0, rm, tm, xa, xb, ya, yb, winding, depth + 1)
        _emit_clipped_span(pts, cx, cy, rm, tm, r1, t1, xa, xb, ya, yb, winding, depth + 1)
        return
    _append_spiral_point(pts, p1, xa, xb, ya, yb, winding)


def _collapse_collinear(
    pts: list[tuple[float, float]],
    eps: float = 1e-4,
) -> list[tuple[float, float]]:
    """Drop vertices that do not turn, keeping reversals."""
    if len(pts) < 3:
        return pts
    out: list[tuple[float, float]] = [pts[0]]
    for i in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[i]
        cx, cy = pts[i + 1]
        abx, aby = bx - ax, by - ay
        bcx, bcy = cx - bx, cy - by
        lab = math.hypot(abx, aby)
        lbc = math.hypot(bcx, bcy)
        if lab < 1e-9:
            continue
        if lbc < 1e-9:
            out.append(pts[i])
            continue
        cross = abx * bcy - aby * bcx
        dot = abx * bcx + aby * bcy
        if abs(cross) > eps * lab * lbc or dot < 0.0:
            out.append(pts[i])
    _append_unique(out, pts[-1])
    return out


def archimedean_spiral_polyline(
    env: FacingEnvelope,
    step_mm: float,
) -> list[tuple[float, float]]:
    """Outside-in Archimedean spiral clipped to the facing rectangle."""
    xa, xb = env.facing_xa, env.facing_xb
    ya, yb = env.facing_ya, env.facing_yb
    step = max(step_mm, 0.05)
    cx = (xa + xb) * 0.5
    cy = (ya + yb) * 0.5
    hx = (xb - xa) * 0.5
    hy = (yb - ya) * 0.5
    # First revolution stays at/above the circumradius so all four corners
    # are clipped onto the envelope before the spiral peels inward.
    r_max = math.hypot(hx, hy) + step
    r_min = min(step * 0.5, r_max * 0.5)
    r_min = max(r_min, 1e-3)
    if r_max <= r_min + 1e-9:
        return [(cx, cy)]

    b = step / (2.0 * math.pi)
    climb = env.milling_direction == MILLING_CLIMB
    sign = -1.0 if climb else 1.0
    winding = _WINDING_CLIMB if climb else _WINDING_CONVENTIONAL
    theta0 = math.atan2(ya - cy, xa - cx)
    theta = theta0
    r = r_max
    pts: list[tuple[float, float]] = []
    n = 0
    prev_r = r
    prev_theta = theta
    while r > r_min and n < _SPIRAL_MAX_POINTS:
        p = _clip_polar_to_rect(cx, cy, r, theta, xa, xb, ya, yb)
        if not pts:
            pts.append(p)
        else:
            _emit_clipped_span(pts, cx, cy, prev_r, prev_theta, r, theta, xa, xb, ya, yb, winding)
        dtheta = _dtheta_for_radius(max(r, math.hypot(p[0] - cx, p[1] - cy)))
        prev_r = r
        prev_theta = theta
        theta += sign * dtheta
        r = r_max - b * abs(theta - theta0)
        n += 1

    if pts:
        last = pts[-1]
        if math.hypot(last[0] - cx, last[1] - cy) > 1e-6:
            pts.append((cx, cy))
    else:
        pts.append((cx, cy))
    return _collapse_collinear(pts)


def facing_layer_xy_paths(
    env: FacingEnvelope,
    step_mm: float,
) -> list[list[PathElement]]:
    """Stay-down XY paths for one Z layer (retract between list entries)."""
    radius = env.path_radius_mm
    retract_between_passes = (
        env.pattern
        in (
            PATTERN_RASTER_X,
            PATTERN_RASTER_Y,
        )
        and env.milling_direction != MILLING_BOTH
    )
    if env.pattern == PATTERN_SPIRAL_ROUND:
        return [fillet_polyline(archimedean_spiral_polyline(env, step_mm), radius)]
    if env.pattern == PATTERN_SPIRAL:
        return [fillet_polyline(rect_spiral_polyline(env, step_mm), radius)]
    if retract_between_passes:
        paths: list[list[PathElement]] = []
        for a, b in iter_raster_passes(env, step_mm):
            paths.append(fillet_polyline((a, b), radius))
        return paths
    return [fillet_polyline(_connected_raster_polyline(env, step_mm), radius)]


def facing_toolpath_xy_polyline(env: FacingEnvelope) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for path in facing_layer_xy_paths(env, env.rough_stepover_mm):
        pts.extend(path_to_preview_xy(path))
    return pts


def generate_facing_gcode(p: FacingParams) -> str:
    lines: list[str] = []
    env = compute_facing_envelope(p)

    z_levels = _rough_z_levels(p)
    total_cut = p.rough_total_depth_mm + p.margin_z_mm
    rough_step = env.rough_stepover_mm
    finish_step = max(p.finish_stepover_mm, 0.05) if p.finish_enabled else rough_step

    lines.append("(Facing)")
    lines.append("(WCS XY origin = stock corner from wizard; Z0 top of stock)")
    lines.append("G21")
    lines.append("G90")
    lines.append("G17")
    lines.append("G94")
    if p.ext_port_enabled:
        lines.append(f"M851 S{p.ext_port_pwm:d}")
    lines.append(f"G0 Z{p.clearance_z_mm:.4f}")
    lines.append(f"M3 S{p.spindle_rpm:.0f}")
    if p.spindle_spinup_dwell_s > 0:
        lines.append(f"G4 P{p.spindle_spinup_dwell_s:d}")

    def emit_layer(z_cut: float, step: float, feed: float, plunge_f: float) -> None:
        first = True
        for elements in facing_layer_xy_paths(env, step):
            if not elements:
                continue
            el0 = elements[0]
            sx, sy = el0.x0, el0.y0
            if first:
                lines.append(f"G0 X{sx:.4f} Y{sy:.4f}")
                lines.append(f"G1 Z{z_cut:.4f} F{plunge_f:.1f}")
                first = False
            else:
                lines.append(f"G0 Z{p.clearance_z_mm:.4f}")
                lines.append(f"G0 X{sx:.4f} Y{sy:.4f}")
                lines.append(f"G1 Z{z_cut:.4f} F{plunge_f:.1f}")
            lines.extend(path_to_gcode(elements, feed))
        lines.append(f"G0 Z{p.clearance_z_mm:.4f}")

    for z_cut in z_levels:
        lines.append(f"(Rough pass Z{z_cut:.4f})")
        emit_layer(
            z_cut,
            rough_step,
            p.rough_feed_mm_min,
            p.rough_plunge_feed_mm_min,
        )

    if p.finish_enabled and p.finish_depth_mm > 1e-6:
        z_fin = -total_cut - p.finish_depth_mm
        lines.append(f"(Finish pass Z{z_fin:.4f})")
        fd = p.finish_feed_mm_min
        pf = min(p.rough_plunge_feed_mm_min, fd)
        emit_layer(z_fin, finish_step, fd, pf)

    lines.append("M5")
    if p.ext_port_enabled:
        lines.append("M852")
    lines.append("G28")
    lines.append("M2")
    return "\n".join(lines) + "\n"
