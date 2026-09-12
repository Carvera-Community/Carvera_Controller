"""Line/arc toolpath primitives, polyline fillets, and G17 G2/G3 emission."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Union

_EPS = 1e-9
_COLLINEAR_ANG = 1e-3
_U_TURN_ANG = math.pi - 1e-3
_PREVIEW_SAGITTA_MM = 0.05


@dataclass(frozen=True)
class Line:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class Arc:
    x0: float
    y0: float
    x1: float
    y1: float
    cx: float
    cy: float
    clockwise: bool


PathElement = Union[Line, Arc]


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _unit(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float, float]:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < _EPS:
        return 0.0, 0.0, 0.0
    return dx / length, dy / length, length


def dedup_points(
    points: Sequence[tuple[float, float]],
    eps: float = 1e-7,
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for x, y in points:
        if not out or math.hypot(x - out[-1][0], y - out[-1][1]) > eps:
            out.append((float(x), float(y)))
    return out


def polyline_to_lines(points: Sequence[tuple[float, float]]) -> list[Line]:
    pts = dedup_points(points)
    lines: list[Line] = []
    for a, b in zip(pts, pts[1:]):
        if _dist(a, b) > _EPS:
            lines.append(Line(a[0], a[1], b[0], b[1]))
    return lines


def fillet_polyline(
    points: Sequence[tuple[float, float]],
    radius: float,
) -> list[PathElement]:
    """Replace in-path corners with circular arcs of at most ``radius``.

    Tangent length is ``R * tan(|turn|/2)``. Adjacent fillets that share a
    segment are scaled so their tangent lengths fit that segment (zigzag
    stepovers therefore cap at half of stepover).
    """
    pts = dedup_points(points)
    if len(pts) < 2:
        return []
    if radius <= _EPS or len(pts) < 3:
        return polyline_to_lines(pts)

    n = len(pts)
    tangents = [0.0] * n
    abs_ang = [0.0] * n
    clockwise = [False] * n
    active = [False] * n

    for i in range(1, n - 1):
        ux, uy, lin = _unit(pts[i - 1], pts[i])
        vx, vy, lout = _unit(pts[i], pts[i + 1])
        if lin < _EPS or lout < _EPS:
            continue
        cross = ux * vy - uy * vx
        dot = ux * vx + uy * vy
        ang = math.atan2(cross, dot)
        aa = abs(ang)
        if aa < _COLLINEAR_ANG or aa > _U_TURN_ANG:
            continue
        tan_half = math.tan(aa / 2.0)
        if tan_half < _EPS:
            continue
        t = min(radius * tan_half, lin, lout)
        if t < 1e-6:
            continue
        tangents[i] = t
        abs_ang[i] = aa
        clockwise[i] = cross < 0.0
        active[i] = True

    for i in range(n - 1):
        seg = _dist(pts[i], pts[i + 1])
        need = 0.0
        if active[i]:
            need += tangents[i]
        if active[i + 1]:
            need += tangents[i + 1]
        if need > seg + 1e-12 and need > _EPS:
            scale = seg / need
            if active[i]:
                tangents[i] *= scale
            if active[i + 1]:
                tangents[i + 1] *= scale

    elements: list[PathElement] = []
    pos = pts[0]
    for i in range(1, n):
        target = pts[i]
        if i < n - 1 and active[i] and tangents[i] > 1e-6:
            ux, uy, _ = _unit(pts[i - 1], pts[i])
            vx, vy, _ = _unit(pts[i], pts[i + 1])
            t = tangents[i]
            tan_half = math.tan(abs_ang[i] / 2.0)
            if tan_half < _EPS:
                if _dist(pos, target) > _EPS:
                    elements.append(Line(pos[0], pos[1], target[0], target[1]))
                pos = target
                continue
            r_arc = t / tan_half
            arc_start = (pts[i][0] - ux * t, pts[i][1] - uy * t)
            arc_end = (pts[i][0] + vx * t, pts[i][1] + vy * t)
            if clockwise[i]:
                nx, ny = uy, -ux
            else:
                nx, ny = -uy, ux
            cx = arc_start[0] + nx * r_arc
            cy = arc_start[1] + ny * r_arc
            if _dist(pos, arc_start) > _EPS:
                elements.append(Line(pos[0], pos[1], arc_start[0], arc_start[1]))
            elements.append(
                Arc(
                    arc_start[0],
                    arc_start[1],
                    arc_end[0],
                    arc_end[1],
                    cx,
                    cy,
                    clockwise[i],
                )
            )
            pos = arc_end
        else:
            if _dist(pos, target) > _EPS:
                elements.append(Line(pos[0], pos[1], target[0], target[1]))
            pos = target
    return elements


def path_to_gcode(elements: Sequence[PathElement], feed: float) -> list[str]:
    """Emit G1 / G2 / G3 (G17 IJK from start) for already-positioned cutter."""
    fword = f"F{feed:.1f}"
    lines: list[str] = []
    for el in elements:
        if isinstance(el, Line):
            lines.append(f"G1 X{el.x1:.4f} Y{el.y1:.4f} {fword}")
        else:
            i_off = el.cx - el.x0
            j_off = el.cy - el.y0
            g = "G2" if el.clockwise else "G3"
            lines.append(f"{g} X{el.x1:.4f} Y{el.y1:.4f} I{i_off:.4f} J{j_off:.4f} {fword}")
    return lines


def _arc_sweep(arc: Arc) -> tuple[float, float, float]:
    """Return (start_angle, signed_sweep, radius). Sweep is negative if clockwise."""
    a0 = math.atan2(arc.y0 - arc.cy, arc.x0 - arc.cx)
    a1 = math.atan2(arc.y1 - arc.cy, arc.x1 - arc.cx)
    r = math.hypot(arc.x0 - arc.cx, arc.y0 - arc.cy)
    if arc.clockwise:
        sweep = a0 - a1
        if sweep <= _EPS:
            sweep += 2.0 * math.pi
        return a0, -sweep, r
    sweep = a1 - a0
    if sweep <= _EPS:
        sweep += 2.0 * math.pi
    return a0, sweep, r


def tessellate_arc(arc: Arc, sagitta_mm: float = _PREVIEW_SAGITTA_MM) -> list[tuple[float, float]]:
    a0, sweep, r = _arc_sweep(arc)
    pts: list[tuple[float, float]] = [(arc.x0, arc.y0)]
    abs_sweep = abs(sweep)
    if r < _EPS or abs_sweep < _EPS:
        pts.append((arc.x1, arc.y1))
        return pts
    sag = max(sagitta_mm, 1e-4)
    try:
        cos_lim = 1.0 - sag / r
        dphi = 2.0 * math.acos(min(1.0, max(-1.0, cos_lim))) if cos_lim > -1.0 else math.pi / 4.0
    except ValueError:
        dphi = math.pi / 8.0
    dphi = min(max(dphi, 1e-3), math.pi / 4.0)
    n = max(2, int(math.ceil(abs_sweep / dphi)))
    sign = 1.0 if sweep > 0.0 else -1.0
    step = abs_sweep / n
    for k in range(1, n):
        ang = a0 + sign * step * k
        pts.append((arc.cx + r * math.cos(ang), arc.cy + r * math.sin(ang)))
    pts.append((arc.x1, arc.y1))
    return pts


def path_to_preview_xy(elements: Sequence[PathElement]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for el in elements:
        if not pts:
            pts.append((el.x0, el.y0))
        if isinstance(el, Line):
            pts.append((el.x1, el.y1))
        else:
            arc_pts = tessellate_arc(el)
            pts.extend(arc_pts[1:])
    return pts
