"""Pure 2D construction math (no Kivy dependency)."""

from __future__ import annotations

import math


def circumcircle_2d(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> tuple[float, float, float]:
    """
    Circle through three XY points (world/canvas plane).
    Returns (cx_out, cy_out, r). Raises ValueError when colinear.
    """
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-14:
        raise ValueError("colinear_points")
    ax2_py2 = ax * ax + ay * ay
    bx2_py2 = bx * bx + by * by
    cx2_py2 = cx * cx + cy * cy
    ux = (ax2_py2 * (by - cy) + bx2_py2 * (cy - ay) + cx2_py2 * (ay - by)) / d
    uy = (ax2_py2 * (cx - bx) + bx2_py2 * (ax - cx) + cx2_py2 * (bx - ax)) / d
    r = ((ux - ax) ** 2 + (uy - ay) ** 2) ** 0.5
    return ux, uy, r


def line_intersection_2d(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    *,
    tol: float = 1e-9,
) -> tuple[float, float] | None:
    """
    Intersection point of infinite line through AB with infinite line through CD.
    Returns None when directions are parallel (including coincident/colinear degeneracy).
    """
    vx, vy = bx - ax, by - ay
    wx, wy = dx - cx, dy - cy
    den = vx * wy - vy * wx
    if abs(den) < tol:
        return None
    qx, qy = cx - ax, cy - ay
    t_num = qx * wy - qy * wx
    t = t_num / den
    return ax + t * vx, ay + t * vy


def circle_line_intersections_2d(
    cx: float,
    cy: float,
    r: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Intersections of a circle (cx, cy, r) with the infinite line through A and B.
    Returns 0, 1, or 2 points sorted by parameter t along the line direction.
    """
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < tol:
        return []
    dx /= length
    dy /= length
    # Translate circle centre to line origin.
    fx, fy = ax - cx, ay - cy
    a = 1.0  # dx*dx + dy*dy normalised
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - r * r
    disc = b * b - 4.0 * a * c
    if disc < 0:
        return []
    if disc < tol * tol:
        t = -b / 2.0
        return [(ax + t * dx, ay + t * dy)]
    sq = math.sqrt(disc)
    t1 = (-b - sq) / 2.0
    t2 = (-b + sq) / 2.0
    return [
        (ax + t1 * dx, ay + t1 * dy),
        (ax + t2 * dx, ay + t2 * dy),
    ]


def circle_circle_intersections_2d(
    cx1: float,
    cy1: float,
    r1: float,
    cx2: float,
    cy2: float,
    r2: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Intersections of two circles. Returns 0, 1, or 2 points.
    """
    d = math.hypot(cx2 - cx1, cy2 - cy1)
    if d < tol:
        return []
    if d > r1 + r2 + tol or d < abs(r1 - r2) - tol:
        return []
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h2 = r1 * r1 - a * a
    if h2 < 0:
        h2 = 0.0
    h = math.sqrt(h2)
    mx = cx1 + a * (cx2 - cx1) / d
    my = cy1 + a * (cy2 - cy1) / d
    rx = -(cy2 - cy1) * (h / d)
    ry = (cx2 - cx1) * (h / d)
    if h < tol:
        return [(mx, my)]
    return [(mx + rx, my + ry), (mx - rx, my - ry)]


def midpoint_2d(
    ax: float, ay: float, bx: float, by: float
) -> tuple[float, float]:
    """Midpoint between two 2D points."""
    return (ax + bx) / 2.0, (ay + by) / 2.0


def tangent_point_to_circle_2d(
    px_: float,
    py_: float,
    cx: float,
    cy: float,
    r: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[float, float]]:
    """
    Tangent touch-points on circle (cx, cy, r) from external point (px_, py_).
    Returns 0 (point inside circle) or 2 touch-points.
    """
    d = math.hypot(px_ - cx, py_ - cy)
    if d < r - tol:
        return []
    if d < tol:
        return []
    # Distance along line P→C to the chord midpoint.
    a = r * r / d
    h2 = r * r - a * a
    if h2 < 0:
        h2 = 0.0
    h = math.sqrt(h2)
    ux, uy = (cx - px_) / d, (cy - py_) / d
    # Chord midpoint.
    mx = px_ + a * ux
    my = py_ + a * uy
    perpx, perpy = -uy, ux
    if h < tol:
        return [(mx, my)]
    return [
        (mx + h * perpx, my + h * perpy),
        (mx - h * perpx, my - h * perpy),
    ]


def tangent_circle_to_circle_external_2d(
    cx1: float,
    cy1: float,
    r1: float,
    cx2: float,
    cy2: float,
    r2: float,
    *,
    tol: float = 1e-9,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    External tangent lines of two non-concentric circles.
    Returns up to 2 tangent lines, each as a pair of touch-points
    ((tx1, ty1), (tx2, ty2)) — one point on each circle.
    For equal radii the lines are parallel and the external centre of similitude
    is at infinity; the touch-points are still well-defined.
    """
    d = math.hypot(cx2 - cx1, cy2 - cy1)
    if d < tol:
        return []

    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []

    # Equal radii: parallel external tangents.
    if abs(r1 - r2) < tol:
        ux, uy = (cx2 - cx1) / d, (cy2 - cy1) / d
        perpx, perpy = -uy, ux
        for sign in (1.0, -1.0):
            t1 = (cx1 + sign * r1 * perpx, cy1 + sign * r1 * perpy)
            t2 = (cx2 + sign * r2 * perpx, cy2 + sign * r2 * perpy)
            lines.append((t1, t2))
        return lines

    # External centre of similitude.
    # S divides C1C2 externally in ratio r1:r2.
    sx = (r1 * cx2 - r2 * cx1) / (r1 - r2)
    sy = (r1 * cy2 - r2 * cy1) / (r1 - r2)

    # Tangent lines from S to circle 1.
    pts = tangent_point_to_circle_2d(sx, sy, cx1, cy1, r1, tol=tol)
    for tp1 in pts:
        # Corresponding touch on circle 2: project onto same tangent line direction.
        dx, dy = tp1[0] - sx, tp1[1] - sy
        L = math.hypot(dx, dy)
        if L < tol:
            continue
        ux, uy = dx / L, dy / L
        # Distance from S to tangent point on circle 2.
        d2 = math.hypot(sx - cx2, sy - cy2)
        a2 = r2 * r2 / d2 if d2 > tol else 0.0
        h2_2 = r2 * r2 - a2 * a2
        if h2_2 < 0:
            h2_2 = 0.0
        h2 = math.sqrt(h2_2)
        mx2 = sx + a2 * (cx2 - sx) / d2
        my2 = sy + a2 * (cy2 - sy) / d2
        perp_x2, perp_y2 = -(cy2 - sy) / d2, (cx2 - sx) / d2
        # Choose the touch-point on circle 2 that is on the same side as tp1.
        tp2_a = (mx2 + h2 * perp_x2, my2 + h2 * perp_y2)
        tp2_b = (mx2 - h2 * perp_x2, my2 - h2 * perp_y2)
        cross_a = (tp2_a[0] - sx) * uy - (tp2_a[1] - sy) * ux
        cross_b = (tp2_b[0] - sx) * uy - (tp2_b[1] - sy) * ux
        cross_ref = (tp1[0] - sx) * uy - (tp1[1] - sy) * ux
        tp2 = tp2_a if abs(cross_a - cross_ref) < abs(cross_b - cross_ref) else tp2_b
        lines.append((tp1, tp2))
    return lines
