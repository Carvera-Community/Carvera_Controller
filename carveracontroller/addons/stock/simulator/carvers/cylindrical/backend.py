"""Cylindrical r(x, θ) dexel carver for wrapping / rotary stock."""

from __future__ import annotations

import math

import numpy as np

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.array_checkpoints import (
    ArrayCheckpointStore,
    restore_array_checkpoint,
)
from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
    compress_array,
    decompress_array,
    keyed_packed_meshes,
    pack_quad_meshes,
    pick_outward_quads,
    quad_normals,
    tile_keys_from_window_mask,
)
from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, TileKey
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LaserDecalMixin,
    LaserMap,
    laser_burn_uint8,
    pick_laser_cell_size_mm,
    split_laser_snapshot,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.simulator.mesh_format import DEFAULT_COLOR
from carveracontroller.addons.stock.stock_geometry import StockBounds, rotate_yz, rotate_yz_np, stock_theta_deg
from carveracontroller.addons.stock.stock_shape import (
    RectangularStock,
    RotaryCylindricalStock,
    StockShape,
)

_EMPTY_R = np.float32(-1.0)
_INF = 1.0e30
# Past-center cuts store r=0. Drawing that pinches every θ vertex onto the
# axis (black shards); dropping those dexels opens a hole in the skin. Inflate
# to this floor at mesh time so the tube stays closed and non-degenerate.
_MIN_SHELL_R = 0.02
# Safety net if a tiny cell_size is passed directly (puck + High used to
# explode to tens of thousands of θ samples).
MAX_CYLINDRICAL_N_THETA = 4096


def shell_floor_radius_mm(cell_size_mm: float) -> float:
    """Smallest remaining radius that still meshes as a closed tube."""
    return max(_MIN_SHELL_R, 0.25 * float(cell_size_mm))


def pick_cylindrical_dims(bounds: StockBounds, cell_size_mm: float, diameter_mm: float) -> tuple[int, int, float]:
    """Return (nx, n_theta, d_theta_deg) so arc length ≈ cell_size."""
    sx = max(bounds.size[0], 1e-6)
    nx = max(1, int(math.ceil(sx / max(cell_size_mm, 1e-9))))
    r = max(0.5 * float(diameter_mm), cell_size_mm)
    circumference = 2.0 * math.pi * r
    n_theta = max(8, int(math.ceil(circumference / max(cell_size_mm, 1e-9))))
    while n_theta % 4 != 0:
        n_theta += 1
    if n_theta > MAX_CYLINDRICAL_N_THETA:
        n_theta = MAX_CYLINDRICAL_N_THETA - (MAX_CYLINDRICAL_N_THETA % 4)
    d_theta = 360.0 / n_theta
    return nx, n_theta, d_theta


def pose_ts_cell_aligned(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    a0: float,
    a1: float,
    *,
    min_x: float,
    cell_size_mm: float,
    d_theta_deg: float,
) -> np.ndarray:
    """``t`` samples at endpoints and at X / θ cell centers the helix crosses.

    Linspace stamps land on cell *edges*, so a V-bit tip splits across two
    cells and the groove floor beats against the (x, θ) grid. Crossing every
    cell center aims the tip at a stored dexel instead.
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    dz = p1[2] - p0[2]
    da = float(a1) - float(a0)
    xyz_len = math.sqrt(dx * dx + dy * dy + dz * dz)
    if xyz_len < 1e-12 and abs(da) < 1e-9:
        return np.array([0.0], dtype=np.float64)

    ts = [0.0, 1.0]
    cell = max(float(cell_size_mm), 1e-9)
    if abs(dx) >= 1e-12:
        lo, hi = (p0[0], p1[0]) if dx > 0.0 else (p1[0], p0[0])
        ix0 = math.ceil((lo - min_x) / cell - 0.5)
        ix1 = math.floor((hi - min_x) / cell - 0.5)
        if ix1 >= ix0:
            wx = min_x + (np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5) * cell
            ts.extend(((wx - p0[0]) / dx).tolist())

    dth = max(float(d_theta_deg), 1e-6)
    if abs(da) >= 1e-9:
        lo_a, hi_a = (float(a0), float(a1)) if da > 0.0 else (float(a1), float(a0))
        k0 = math.ceil(lo_a / dth - 0.5)
        k1 = math.floor(hi_a / dth - 0.5)
        if k1 >= k0:
            ac = (np.arange(k0, k1 + 1, dtype=np.float64) + 0.5) * dth
            ts.extend(((ac - float(a0)) / da).tolist())

    arr = np.unique(np.round(np.clip(np.asarray(ts, dtype=np.float64), 0.0, 1.0), 10))
    if arr.size < 2:
        return np.array([0.0, 1.0], dtype=np.float64)
    return arr


def _sample_profile_radius(profile_zs: np.ndarray, profile_rs: np.ndarray, z_rel: np.ndarray) -> np.ndarray:
    """Profile radius at tool-relative Z (vectorized)."""
    if profile_zs.size == 0:
        return np.zeros_like(z_rel, dtype=np.float64)
    flat = z_rel.ravel()
    out = np.zeros_like(flat, dtype=np.float64)
    below = flat < profile_zs[0] - 1e-9
    above = flat > profile_zs[-1] + 1e-9
    mid = ~(below | above)
    if mid.any():
        idx = np.searchsorted(profile_zs, flat[mid], side="right") - 1
        idx = np.clip(idx, 0, len(profile_zs) - 2)
        z0 = profile_zs[idx]
        z1 = profile_zs[idx + 1]
        r0 = profile_rs[idx]
        r1 = profile_rs[idx + 1]
        denom = z1 - z0
        t = np.zeros_like(flat[mid], dtype=np.float64)
        nonzero = np.abs(denom) >= 1e-12
        if nonzero.any():
            t[nonzero] = (flat[mid][nonzero] - z0[nonzero]) / denom[nonzero]
        out[mid] = r0 + t * (r1 - r0)
    return out.reshape(z_rel.shape)


def _xyz_inside_tool(
    XX: np.ndarray,
    YY: np.ndarray,
    ZZ: np.ndarray,
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    profile_zs: np.ndarray,
    profile_rs: np.ndarray,
    const_r: float | None,
    max_r: float,
) -> np.ndarray:
    """True where a point is inside the tool swept along ``p0→p1`` (constant A)."""
    XX, YY, ZZ = np.broadcast_arrays(
        np.asarray(XX, dtype=np.float64),
        np.asarray(YY, dtype=np.float64),
        np.asarray(ZZ, dtype=np.float64),
    )
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    dz = p1[2] - p0[2]
    xy_len_sq = dx * dx + dy * dy
    seg_len_sq = xy_len_sq + dz * dz
    z0 = float(profile_zs[0]) if profile_zs.size else 0.0
    z1 = float(profile_zs[-1]) if profile_zs.size else 0.0
    eps = 1e-9

    def _inside_from_xy(
        window_ok: np.ndarray,
        dist_xy: np.ndarray,
        *,
        z_rel: np.ndarray | None = None,
        band_lo: np.ndarray | None = None,
        band_hi: np.ndarray | None = None,
    ) -> np.ndarray:
        window_ok, dist_xy = np.broadcast_arrays(window_ok, dist_xy)
        candidate = window_ok & (dist_xy <= max_r + eps)
        if not np.any(candidate):
            return np.zeros(candidate.shape, dtype=bool)
        if const_r is not None:
            return candidate if const_r > 0.0 else np.zeros(candidate.shape, dtype=bool)
        radii = np.zeros(candidate.shape, dtype=np.float64)
        if band_lo is not None and band_hi is not None:
            lo_b, hi_b, cand_b = np.broadcast_arrays(band_lo, band_hi, candidate)
            r_lo = _sample_profile_radius(profile_zs, profile_rs, lo_b)
            r_hi = _sample_profile_radius(profile_zs, profile_rs, hi_b)
            radii = np.maximum(r_lo, r_hi)
            if profile_zs.size > 2:
                for z in profile_zs[1:-1]:
                    in_band = cand_b & (float(z) >= lo_b - 1e-9) & (float(z) <= hi_b + 1e-9)
                    if not in_band.any():
                        continue
                    r_k = _sample_profile_radius(profile_zs, profile_rs, np.full_like(lo_b, float(z)))
                    radii = np.where(in_band, np.maximum(radii, r_k), radii)
            dist_b = np.broadcast_to(dist_xy, cand_b.shape)
            return cand_b & (dist_b <= radii + eps) & (radii > 0.0)
        if z_rel is None:
            return np.zeros(candidate.shape, dtype=bool)
        z_b, cand_b = np.broadcast_arrays(z_rel, candidate)
        radii[cand_b] = _sample_profile_radius(profile_zs, profile_rs, z_b[cand_b])
        dist_b = np.broadcast_to(dist_xy, cand_b.shape)
        return cand_b & (dist_b <= radii + eps) & (radii > 0.0)

    if seg_len_sq < 1e-18:
        z_rel = ZZ - p0[2]
        dist_xy = np.hypot(XX - p0[0], YY - p0[1])
        if profile_zs.size:
            window_ok = (z_rel >= z0 - eps) & (z_rel <= z1 + eps)
        else:
            window_ok = np.zeros(ZZ.shape, dtype=bool)
        return _inside_from_xy(window_ok, dist_xy, z_rel=z_rel)

    if xy_len_sq < 1e-18:
        tip_z_lo = min(p0[2], p0[2] + dz)
        tip_z_hi = max(p0[2], p0[2] + dz)
        band_lo = np.maximum(ZZ - tip_z_hi, z0)
        band_hi = np.minimum(ZZ - tip_z_lo, z1)
        window_ok = band_lo <= band_hi + eps
        dist_xy = np.hypot(XX - p0[0], YY - p0[1])
        return _inside_from_xy(window_ok, dist_xy, band_lo=band_lo, band_hi=band_hi)

    if abs(dz) < 1e-18:
        z_rel_fixed = ZZ - p0[2]
        window_ok = (z_rel_fixed >= z0 - eps) & (z_rel_fixed <= z1 + eps)
        t_lo = np.where(window_ok, 0.0, 1.0)
        t_hi = np.where(window_ok, 1.0, 0.0)
    else:
        t_a = (ZZ - z1 - p0[2]) / dz
        t_b = (ZZ - z0 - p0[2]) / dz
        t_lo = np.maximum(np.minimum(t_a, t_b), 0.0)
        t_hi = np.minimum(np.maximum(t_a, t_b), 1.0)
        window_ok = t_lo <= t_hi + eps

    t = ((XX - p0[0]) * dx + (YY - p0[1]) * dy) / xy_len_sq
    t = np.minimum(np.maximum(t, t_lo), t_hi)
    tip_x = p0[0] + t * dx
    tip_y = p0[1] + t * dy
    tip_z = p0[2] + t * dz
    z_rel = ZZ - tip_z
    dist_xy = np.hypot(XX - tip_x, YY - tip_y)
    return _inside_from_xy(window_ok, dist_xy, z_rel=z_rel)


def _cylinder_s_interval(
    wx: np.ndarray,
    uy: np.ndarray,
    uz: np.ndarray,
    y0: float,
    z0_axis: float,
    tip: tuple[float, float, float],
    radius: float,
    flute_z0: float,
    flute_z1: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """s-interval where a dexel is inside a Z-aligned finite cylinder."""
    tx, ty, tz = float(tip[0]), float(tip[1]), float(tip[2])
    r_tool = float(radius)
    z_lo = tz + float(flute_z0)
    z_hi = tz + float(flute_z1)
    if z_hi < z_lo:
        z_lo, z_hi = z_hi, z_lo

    dx = wx - tx
    bud = r_tool * r_tool - dx * dx
    bud_b = bud[:, None]
    q = y0 - ty
    uy_b = uy[None, :]
    uz_b = uz[None, :]

    u_fixed = np.abs(uy_b) < 1e-12
    disc = np.sqrt(np.maximum(bud_b, 0.0))
    uy_safe = np.where(u_fixed, 1.0, uy_b)
    s_a = (-q - disc) / uy_safe
    s_b = (-q + disc) / uy_safe
    s_xy_lo = np.minimum(s_a, s_b)
    s_xy_hi = np.maximum(s_a, s_b)
    no_xy = bud_b < -1e-12
    s_xy_lo = np.where(no_xy, _INF, s_xy_lo)
    s_xy_hi = np.where(no_xy, -_INF, s_xy_hi)
    inside_u_fixed = (q * q) <= (bud_b + 1e-12)
    s_xy_lo = np.where(u_fixed, np.where(inside_u_fixed, -_INF, _INF), s_xy_lo)
    s_xy_hi = np.where(u_fixed, np.where(inside_u_fixed, _INF, -_INF), s_xy_hi)

    z_fixed = np.abs(uz_b) < 1e-12
    inside_z_fixed = (z_lo - 1e-9) <= z0_axis <= (z_hi + 1e-9)
    uz_safe = np.where(z_fixed, 1.0, uz_b)
    sz_a = (z_lo - z0_axis) / uz_safe
    sz_b = (z_hi - z0_axis) / uz_safe
    s_z_lo = np.minimum(sz_a, sz_b)
    s_z_hi = np.maximum(sz_a, sz_b)
    s_z_lo = np.where(z_fixed, np.where(inside_z_fixed, -_INF, _INF), s_z_lo)
    s_z_hi = np.where(z_fixed, np.where(inside_z_fixed, _INF, -_INF), s_z_hi)

    s_enter = np.maximum(np.maximum(s_xy_lo, s_z_lo), 0.0)
    s_exit = np.minimum(s_xy_hi, s_z_hi)
    valid = s_enter <= s_exit + 1e-9
    return s_enter, s_exit, valid


def _hit_from_s_interval(
    s_enter: np.ndarray,
    s_exit: np.ndarray,
    valid: np.ndarray,
    s_hi: np.ndarray,
    probe: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Outside-in remaining radius from a dexel/tool s-interval."""
    s_probe = np.maximum(s_hi - probe, 0.0)
    inside_hi = valid & (s_hi >= s_enter - 1e-9) & (s_hi <= s_exit + 1e-9)
    inside_pr = valid & (s_probe >= s_enter - 1e-9) & (s_probe <= s_exit + 1e-9)
    hit = (s_hi >= 0.0) & (inside_hi | inside_pr)
    new_s = np.where(hit, s_enter, s_hi)
    return new_s, hit


def _cylinder_cut_radius(
    wx: np.ndarray,
    uy: np.ndarray,
    uz: np.ndarray,
    y0: float,
    z0_axis: float,
    tip: tuple[float, float, float],
    radius: float,
    flute_z0: float,
    flute_z1: float,
    s_hi: np.ndarray,
    probe: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Outside-in remaining dexel radius vs a Z-aligned finite cylinder.

    Each dexel is the ray ``(wx, y0 + s·uy, z0_axis + s·uz)``. Returns
    ``(new_s, hit)``; ``hit`` is true when the current surface (or a one-cell
    inward probe) lies in the tool, so internal cavities are not punched.
    """
    s_enter, s_exit, valid = _cylinder_s_interval(wx, uy, uz, y0, z0_axis, tip, radius, flute_z0, flute_z1)
    return _hit_from_s_interval(s_enter, s_exit, valid, s_hi, probe)


def _profile_segments(profile_zs: np.ndarray, profile_rs: np.ndarray) -> list[tuple[float, float, float, float]]:
    """Non-degenerate (z, r) frustum segments, z increasing."""
    segs: list[tuple[float, float, float, float]] = []
    n = int(profile_zs.size)
    for i in range(n - 1):
        za, zb = float(profile_zs[i]), float(profile_zs[i + 1])
        ra, rb = float(profile_rs[i]), float(profile_rs[i + 1])
        if abs(zb - za) < 1e-12 and abs(rb - ra) < 1e-12:
            continue
        if zb < za:
            za, zb, ra, rb = zb, za, rb, ra
        segs.append((za, zb, ra, rb))
    return segs


def _clip_s_interval(
    lo_a: np.ndarray | float,
    hi_a: np.ndarray | float,
    lo_b: np.ndarray | float,
    hi_b: np.ndarray | float,
) -> tuple[np.ndarray, np.ndarray]:
    return np.maximum(lo_a, lo_b), np.minimum(hi_a, hi_b)


def _frustum_s_intervals(
    wx: np.ndarray,
    uy: np.ndarray,
    uz: np.ndarray,
    y0: float,
    z0_axis: float,
    tip: tuple[float, float, float],
    za: float,
    zb: float,
    ra: float,
    rb: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Up to two s-intervals where a dexel is inside a truncated cone.

    Returns ``(lo1, hi1, ok1, lo2, hi2, ok2)``. Slot 2 is empty unless the
    infinite-cone quadratic opens down and the Z-slab overlaps both wings.
    """
    tx, ty, tz = float(tip[0]), float(tip[1]), float(tip[2])
    dx = (wx - tx)[:, None]
    q = y0 - ty
    uy_b = uy[None, :]
    uz_b = uz[None, :]
    z_lo = tz + float(za)
    z_hi = tz + float(zb)
    empty_lo = np.full((wx.size, uy.size), _INF)
    empty_hi = np.full((wx.size, uy.size), -_INF)

    z_fixed = np.abs(uz_b) < 1e-12
    inside_z_fixed = (z_lo - 1e-9) <= z0_axis <= (z_hi + 1e-9)
    uz_safe = np.where(z_fixed, 1.0, uz_b)
    sz_a = (z_lo - z0_axis) / uz_safe
    sz_b = (z_hi - z0_axis) / uz_safe
    s_z_lo = np.minimum(sz_a, sz_b)
    s_z_hi = np.maximum(sz_a, sz_b)
    s_z_lo = np.where(z_fixed, np.where(inside_z_fixed, -_INF, _INF), s_z_lo)
    s_z_hi = np.where(z_fixed, np.where(inside_z_fixed, _INF, -_INF), s_z_hi)

    dz = float(zb) - float(za)
    k = 0.0 if abs(dz) < 1e-12 else (float(rb) - float(ra)) / dz
    # r(s) = A + B·s along the dexel (linear interpolation of the profile).
    A = float(ra) + k * (z0_axis - tz - float(za))
    B = k * uz_b

    b_fixed = np.abs(B) < 1e-12
    r_pos_fixed = A >= -1e-12
    B_safe = np.where(b_fixed, 1.0, B)
    s_r0 = -A / B_safe
    s_r_lo = np.where(b_fixed, np.where(r_pos_fixed, -_INF, _INF), np.where(B > 0.0, s_r0, -_INF))
    s_r_hi = np.where(b_fixed, np.where(r_pos_fixed, _INF, -_INF), np.where(B > 0.0, _INF, s_r0))

    box_lo, box_hi = _clip_s_interval(s_z_lo, s_z_hi, s_r_lo, s_r_hi)
    box_lo = np.maximum(box_lo, 0.0)
    box_ok = box_lo <= box_hi + 1e-9

    # rho(s)^2 <= r(s)^2  →  cs2 s^2 + cs1 s + cs0 <= 0
    cs2 = uy_b * uy_b - B * B
    cs1 = 2.0 * q * uy_b - 2.0 * A * B
    cs0 = dx * dx + q * q - A * A
    lin = np.abs(cs2) < 1e-14
    disc_raw = cs1 * cs1 - 4.0 * cs2 * cs0
    disc = np.maximum(disc_raw, 0.0)
    sqrt_d = np.sqrt(disc)
    cs2_safe = np.where(lin, 1.0, cs2)
    inv = 0.5 / cs2_safe
    r1 = (-cs1 - sqrt_d) * inv
    r2 = (-cs1 + sqrt_d) * inv
    root_lo = np.minimum(r1, r2)
    root_hi = np.maximum(r1, r2)

    lo1, hi1 = empty_lo.copy(), empty_hi.copy()
    lo2, hi2 = empty_lo.copy(), empty_hi.copy()

    always_in = (~lin) & (disc_raw < -1e-12) & (cs2 < 0.0) & box_ok
    lo1 = np.where(always_in, box_lo, lo1)
    hi1 = np.where(always_in, box_hi, hi1)

    up = (~lin) & (cs2 >= 0.0) & (disc_raw >= -1e-12) & box_ok
    u_lo, u_hi = _clip_s_interval(box_lo, box_hi, root_lo, root_hi)
    u_ok = up & (u_lo <= u_hi + 1e-9)
    lo1 = np.where(u_ok, u_lo, lo1)
    hi1 = np.where(u_ok, u_hi, hi1)

    down = (~lin) & (cs2 < 0.0) & (disc_raw >= -1e-12) & box_ok
    w1_lo, w1_hi = _clip_s_interval(box_lo, box_hi, -_INF, root_lo)
    w2_lo, w2_hi = _clip_s_interval(box_lo, box_hi, root_hi, _INF)
    v1 = down & (w1_lo <= w1_hi + 1e-9)
    v2 = down & (w2_lo <= w2_hi + 1e-9)
    both = v1 & v2
    lo1 = np.where(v1, w1_lo, lo1)
    hi1 = np.where(v1, w1_hi, hi1)
    lo1 = np.where((~v1) & v2, w2_lo, lo1)
    hi1 = np.where((~v1) & v2, w2_hi, hi1)
    lo2 = np.where(both, w2_lo, lo2)
    hi2 = np.where(both, w2_hi, hi2)

    c1_fixed = np.abs(cs1) < 1e-14
    inside_lin_fixed = cs0 <= 1e-12
    cs1_safe = np.where(c1_fixed, 1.0, cs1)
    s_lin = -cs0 / cs1_safe
    s_lin_lo = np.where(c1_fixed, np.where(inside_lin_fixed, -_INF, _INF), np.where(cs1 > 0.0, -_INF, s_lin))
    s_lin_hi = np.where(c1_fixed, np.where(inside_lin_fixed, _INF, -_INF), np.where(cs1 > 0.0, s_lin, _INF))
    l_lo, l_hi = _clip_s_interval(box_lo, box_hi, s_lin_lo, s_lin_hi)
    l_ok = lin & box_ok & (l_lo <= l_hi + 1e-9)
    lo1 = np.where(l_ok, l_lo, lo1)
    hi1 = np.where(l_ok, l_hi, hi1)

    ok1 = lo1 <= hi1 + 1e-9
    ok2 = lo2 <= hi2 + 1e-9
    return lo1, hi1, ok1, lo2, hi2, ok2


def _revolution_cut_radius(
    wx: np.ndarray,
    uy: np.ndarray,
    uz: np.ndarray,
    y0: float,
    z0_axis: float,
    tip: tuple[float, float, float],
    profile_zs: np.ndarray,
    profile_rs: np.ndarray,
    s_hi: np.ndarray,
    probe: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Outside-in remaining dexel radius vs a Z-aligned tool of revolution.

    Piecewise-linear profiles (V-bit / chamfer / taper) become truncated cones.
    Overlapping frustum intervals that contain the current surface are merged
    so a cone+cylinder bit still cuts down to the first entry from the axis.
    """
    segs = _profile_segments(profile_zs, profile_rs)
    if not segs:
        return s_hi, np.zeros(s_hi.shape, dtype=bool)
    if len(segs) == 1 and abs(segs[0][2] - segs[0][3]) < 1e-12:
        za, zb, ra, _rb = segs[0]
        return _cylinder_cut_radius(wx, uy, uz, y0, z0_axis, tip, ra, za, zb, s_hi, probe)

    slots: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for za, zb, ra, rb in segs:
        if abs(rb - ra) < 1e-12:
            lo, hi, ok = _cylinder_s_interval(wx, uy, uz, y0, z0_axis, tip, ra, za, zb)
            slots.append((lo, hi, ok))
            continue
        lo1, hi1, ok1, lo2, hi2, ok2 = _frustum_s_intervals(wx, uy, uz, y0, z0_axis, tip, za, zb, ra, rb)
        slots.append((lo1, hi1, ok1))
        if ok2.any():
            slots.append((lo2, hi2, ok2))

    if not slots:
        return s_hi, np.zeros(s_hi.shape, dtype=bool)
    if len(slots) == 1:
        return _hit_from_s_interval(slots[0][0], slots[0][1], slots[0][2], s_hi, probe)

    los = np.stack([lo for lo, _hi, _ok in slots])
    his = np.stack([hi for _lo, hi, _ok in slots])
    oks = np.stack([ok for _lo, _hi, ok in slots])
    s_probe = np.maximum(s_hi - probe, 0.0)
    contains = oks & (
        ((s_hi >= los - 1e-9) & (s_hi <= his + 1e-9)) | ((s_probe >= los - 1e-9) & (s_probe <= his + 1e-9))
    )
    hit = np.any(contains, axis=0) & (s_hi >= 0.0)
    enter = np.min(np.where(contains, los, _INF), axis=0)
    exit_ = np.max(np.where(contains, his, -_INF), axis=0)
    for _ in range(len(slots) - 1):
        overlap = oks & (los <= exit_ + 1e-9) & (his >= enter - 1e-9)
        overlap &= hit
        enter = np.minimum(enter, np.min(np.where(overlap, los, _INF), axis=0))
        exit_ = np.maximum(exit_, np.max(np.where(overlap, his, -_INF), axis=0))
    new_s = np.where(hit, np.maximum(enter, 0.0), s_hi)
    return new_s, hit


class CylindricalBackend(LaserDecalMixin):
    """Remaining outer radius per (x, θ) cell around the A-axis."""

    kind = "cylindrical"

    def __init__(
        self,
        bounds: StockBounds,
        cell_size_mm: float,
        shape: StockShape | None = None,
        tile_size: int = DEFAULT_TILE_SIZE,
        *,
        radii: np.ndarray | None = None,
        seed: bool = True,
        index_origin_x: int = 0,
        laser_cell_size_mm: float | None = None,
    ):
        self.bounds = bounds
        self.cell_size = float(cell_size_mm)
        self._laser_cell_size = (
            float(laser_cell_size_mm)
            if laser_cell_size_mm is not None
            else pick_laser_cell_size_mm(bounds, self.cell_size, cylindrical=True)
        )
        self.tile_size = max(2, int(tile_size))
        self.shape: StockShape = shape or RotaryCylindricalStock(
            diameter_mm=max(min(bounds.size[1], bounds.size[2]), 1e-6),
            length_mm=max(bounds.size[0], 1e-6),
        )
        if isinstance(self.shape, RotaryCylindricalStock):
            diameter = float(self.shape.diameter_mm)
        else:
            diameter = min(bounds.size[1], bounds.size[2])
        self.axis_y = 0.5 * (bounds.min_y + bounds.max_y)
        self.axis_z = 0.5 * (bounds.min_z + bounds.max_z)
        self.stock_radius = 0.5 * diameter
        self.nx, self.n_theta, self.d_theta = pick_cylindrical_dims(bounds, self.cell_size, diameter)
        self.n_tiles_x = max(1, int(math.ceil(self.nx / self.tile_size)))
        self.n_tiles_theta = max(1, int(math.ceil(self.n_theta / self.tile_size)))
        self._ox = int(index_origin_x)
        self._touched: set[TileKey] = set()
        half = (np.arange(self.n_theta, dtype=np.float64) + 0.5) * self.d_theta
        rad = np.deg2rad(half)
        self._sin_t = np.sin(rad)
        self._cos_t = np.cos(rad)
        if radii is not None:
            self.radii = radii
        else:
            self._ox = 0
            self.radii = np.full((self.nx, self.n_theta), _EMPTY_R, dtype=np.float32)
            if seed:
                self._seed_radii()
        self._init_laser()

    def _fill_seed(self, out: np.ndarray) -> None:
        if isinstance(self.shape, RotaryCylindricalStock):
            out[:, :] = np.float32(self.stock_radius)
            return
        if isinstance(self.shape, RectangularStock):
            hy = 0.5 * float(self.shape.length_mm)
            hz = 0.5 * float(self.shape.height_mm)
            dy = self._sin_t
            dz = self._cos_t
            t = np.full(self.n_theta, self.stock_radius, dtype=np.float64)
            mask_y = np.abs(dy) > 1e-12
            mask_z = np.abs(dz) > 1e-12
            cand = np.full(self.n_theta, np.inf, dtype=np.float64)
            cand[mask_y] = hy / np.abs(dy[mask_y])
            cand_z = np.full(self.n_theta, np.inf, dtype=np.float64)
            cand_z[mask_z] = hz / np.abs(dz[mask_z])
            t = np.minimum(cand, cand_z)
            t[~np.isfinite(t)] = self.stock_radius
            out[:, :] = t.astype(np.float32)
            return
        out[:, :] = np.float32(self.stock_radius)

    def _seed_radii(self) -> None:
        self._fill_seed(self.radii)

    def reset_occupancy(self) -> set[TileKey]:
        self.radii[:, :] = _EMPTY_R
        self._ox = 0
        self._seed_radii()
        self._touched.clear()
        self._drop_laser()
        return self.initial_surface_keys()

    def clone_empty(self) -> CylindricalBackend:
        return CylindricalBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.tile_size,
            seed=True,
            laser_cell_size_mm=self._laser_cell_size,
        )

    def _make_laser_map(self) -> LaserMap:
        diameter = 2.0 * self.stock_radius
        nx, n_theta, d_theta = pick_cylindrical_dims(self.bounds, self._laser_cell_size, diameter)
        return LaserMap.cylindrical(self.bounds, nx, n_theta, self._laser_cell_size, d_theta)

    def _clear_laser_indexed(self, ix0: int, it: np.ndarray, changed: np.ndarray) -> None:
        if self._laser is None:
            return
        if self._laser.clear_from_coarse_mask(
            changed,
            ix0,
            it,
            self.cell_size,
            self.d_theta,
            self.bounds.min_x,
            0.0,
            coarse_nv=self.n_theta,
        ):
            self._laser_dirty = True

    def _stock_theta(self, p: tuple[float, float, float], angle_deg: float) -> float:
        return stock_theta_deg(p[1], p[2], angle_deg, self.axis_y, self.axis_z)

    def _laser_allow_from_radii(
        self,
        laser: LaserMap,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        theta0: float,
        theta1: float,
        radius: float,
        min_r: float,
    ) -> tuple[np.ndarray | None, tuple[int, int] | None]:
        if self.radii.shape != (self.nx, self.n_theta):
            return None, None
        pad_u = radius + laser.cell_u
        pad_v = radius / max(laser.v_scale, 1e-12) + laser.cell_v
        iu0 = max(0, int(math.floor((min(p0[0], p1[0]) - pad_u - laser.origin_u) / laser.cell_u)))
        iu1 = min(laser.nx - 1, int(math.floor((max(p0[0], p1[0]) + pad_u - laser.origin_u) / laser.cell_u)))
        if iu0 > iu1:
            return None, None
        uu = laser.origin_u + (np.arange(iu0, iu1 + 1, dtype=np.float64) + 0.5) * laser.cell_u
        ix = np.clip(
            np.floor((uu - self.bounds.min_x) / self.cell_size).astype(np.int32),
            0,
            self.nx - 1,
        )
        iv_idx = laser._wrapped_v_indices(float(theta0), float(theta1), pad_v)
        if iv_idx.size == 0:
            return None, None
        period = laser.v_period if laser.v_period else 360.0
        vv = laser.origin_v + (iv_idx.astype(np.float64) + 0.5) * laser.cell_v
        it = np.floor(np.mod(vv, period) / max(self.d_theta, 1e-12)).astype(np.int32) % self.n_theta
        occ = self.radii[ix[:, None], it[None, :]]
        eps = max(self.cell_size, 0.2)
        window = (occ >= 0.0) & (occ >= np.float32(min_r - eps))
        allow = np.zeros((iu1 - iu0 + 1, laser.nv), dtype=bool)
        allow[:, iv_idx % laser.nv] = window
        return allow, (iu0, 0)

    def engrave_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def=None,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
        power_s: float | None = None,
    ) -> bool:
        del tool_def, tool_unit_scale
        burn = laser_burn_uint8(power_s)
        if not burn:
            return False
        radius = stroke_radius_mm(self._laser_cell_size)
        d0 = math.hypot(p0[1] - self.axis_y, p0[2] - self.axis_z)
        d1 = math.hypot(p1[1] - self.axis_y, p1[2] - self.axis_z)
        min_r = min(d0, d1)
        theta0 = self._stock_theta(p0, a0)
        theta1 = self._stock_theta(p1, a1)
        laser = self._ensure_laser()
        allow, origin = self._laser_allow_from_radii(laser, p0, p1, theta0, theta1, radius, min_r)
        changed = laser.paint_segment(
            p0[0],
            theta0,
            p1[0],
            theta1,
            radius,
            allow,
            allow_origin=origin,
            burn=burn,
        )
        if changed:
            self._laser_dirty = True
        elif self._laser is not None and not np.any(self._laser.intensity):
            self._drop_laser()
        return changed

    def _x_index(self, x: float) -> int:
        return int(math.floor((x - self.bounds.min_x) / self.cell_size))

    def _theta_index(self, angle_deg: float) -> int:
        a = angle_deg % 360.0
        if a < 0:
            a += 360.0
        return int(a / self.d_theta) % self.n_theta

    def carve_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
    ) -> set[TileKey]:
        profile = resolve_cutting_profile(tool_def, tool_unit_scale=tool_unit_scale)
        if not profile:
            return set()
        max_r = max(r for _z, r in profile)
        flute_z = profile[-1][0]
        if max_r <= 0 and flute_z <= 0:
            return set()
        profile_zs = np.array([z for z, _r in profile], dtype=np.float64)
        profile_rs = np.array([r for _z, r in profile], dtype=np.float64)
        const_r = None
        if float(np.max(profile_rs) - np.min(profile_rs)) < 1e-12:
            const_r = float(profile_rs[0])

        a0 = float(a0)
        a1 = float(a1)
        da = a1 - a0
        dxs = p1[0] - p0[0]
        dys = p1[1] - p0[1]
        dzs = p1[2] - p0[2]
        step_a = float(self.d_theta)
        args = (profile_zs, profile_rs, const_r, max_r)

        # Indexed (tiny ΔA): one swept XYZ test. Wrapping / tight helix: pose
        # samples into one buffer. Shallow helix (a few θ cells over a long X):
        # a handful of swept chunks — cheaper than one sample per XYZ cell.
        # A full turn at constant XYZ cuts every θ the same way — one pose plus
        # a ring broadcast, not one sample per degree.
        xyz_len_sq = dxs * dxs + dys * dys + dzs * dzs
        if abs(da) >= 360.0 - 1e-6 and xyz_len_sq <= self.cell_size * self.cell_size:
            tip = p0 if xyz_len_sq < 1e-18 else (p0[0] + 0.5 * dxs, p0[1] + 0.5 * dys, p0[2] + 0.5 * dzs)
            return self._carve_full_revolution(tip, 0.5 * (a0 + a1), *args)
        if abs(da) <= step_a + 1e-9:
            return self._carve_constant_a(p0, p1, 0.5 * (a0 + a1), *args)
        n_a = int(math.ceil(abs(da) / step_a)) + 1
        if n_a > 4:
            return self._carve_moving_a(p0, p1, a0, a1, *args)
        n = max(1, int(math.ceil(abs(da) / step_a)))
        dirty: set[TileKey] = set()
        for i in range(n):
            t0 = i / n
            t1 = (i + 1) / n
            pi0 = (p0[0] + t0 * dxs, p0[1] + t0 * dys, p0[2] + t0 * dzs)
            pi1 = (p0[0] + t1 * dxs, p0[1] + t1 * dys, p0[2] + t1 * dzs)
            dirty |= self._carve_constant_a(pi0, pi1, a0 + 0.5 * (t0 + t1) * da, *args)
        return dirty

    def _theta_window_indices(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        angle: float,
        max_r: float,
    ) -> np.ndarray:
        """Conservative θ cells the cutter may overlap at this A.

        Centered on the tool's machine-frame YZ azimuth about the (rotated)
        axis — stock θ = atan2(Y, Z) − A when the axis is at the origin.
        Pads from the closest YZ approach to the axis. A disk that overlaps
        the axis, or a segment that passes near it, tests every θ.
        """
        y_axis, z_axis = rotate_yz(self.axis_y, self.axis_z, -angle)
        dy0 = p0[1] - y_axis
        dz0 = p0[2] - z_axis
        dy1 = p1[1] - y_axis
        dz1 = p1[2] - z_axis
        vx = dy1 - dy0
        vz = dz1 - dz0
        len_sq = vx * vx + vz * vz
        if len_sq < 1e-18:
            min_dist = math.hypot(dy0, dz0)
        else:
            t = max(0.0, min(1.0, -(dy0 * vx + dz0 * vz) / len_sq))
            min_dist = math.hypot(dy0 + t * vx, dz0 + t * vz)
        reach = max_r + self.cell_size
        if min_dist < reach + 1e-9:
            return np.arange(self.n_theta, dtype=np.int32)
        pad = math.degrees(math.asin(min(1.0, reach / min_dist))) + self.d_theta
        th0 = stock_theta_deg(p0[1], p0[2], angle, self.axis_y, self.axis_z)
        th1 = stock_theta_deg(p1[1], p1[2], angle, self.axis_y, self.axis_z)
        delta = (th1 - th0 + 180.0) % 360.0 - 180.0
        lo = min(th0, th0 + delta) - pad
        hi = max(th0, th0 + delta) + pad
        return self._theta_indices(lo, hi)

    def _ray_frame(self, it: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray, float, float]:
        uy, uz = rotate_yz_np(self._sin_t[it], self._cos_t[it], -angle)
        y0, z0 = rotate_yz(self.axis_y, self.axis_z, -angle)
        return uy, uz, float(y0), float(z0)

    def _radius_search_iters(self) -> int:
        step = max(self.cell_size * 0.02, 1e-5)
        ratio = max(self.stock_radius, self.cell_size) / step
        return int(min(14, max(8, math.ceil(math.log2(ratio)) + 1)))

    def _theta_indices(self, a_start: float, a_end: float) -> np.ndarray:
        """Theta indices covering ``[a_start, a_end]`` degrees (may wrap)."""
        span = float(a_end) - float(a_start)
        if span < 0.0:
            a_start, a_end = a_end, a_start
            span = -span
        n_th = self.n_theta
        if span >= 360.0 - 1e-6:
            return np.arange(n_th, dtype=np.int32)
        i0 = self._theta_index(a_start)
        n = int(math.ceil(span / self.d_theta)) + 2
        if n + 1 >= n_th:
            return np.arange(n_th, dtype=np.int32)
        return (i0 + np.arange(n + 1, dtype=np.int32)) % n_th

    def _dirty_from_mask(self, changed: np.ndarray, ix0: int, it: np.ndarray) -> set[TileKey]:
        if changed.size == 0 or not changed.any():
            return set()
        ts = self.tile_size
        rows = np.flatnonzero(np.any(changed, axis=1))
        cols = np.flatnonzero(np.any(changed, axis=0))
        tx = np.unique((rows + int(ix0)) // ts)
        ty = np.unique(it[cols] // ts)
        return {(int(x), int(y), 0) for x in tx for y in ty}

    def _write_slab(self, ix0: int, it: np.ndarray, slab: np.ndarray, changed: np.ndarray) -> set[TileKey]:
        if not changed.any():
            return set()
        ix = np.arange(ix0, ix0 + slab.shape[0])
        self.radii[ix[:, None], it[None, :]] = slab.astype(np.float32, copy=False)
        self._clear_laser_indexed(ix0, it, changed)
        dirty = self._dirty_from_mask(changed, ix0, it)
        self._touched |= dirty
        return dirty

    def _cut_slab(
        self,
        slab: np.ndarray,
        wx: np.ndarray,
        it: np.ndarray,
        angle: float,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        profile_zs: np.ndarray,
        profile_rs: np.ndarray,
        const_r: float | None,
        max_r: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(new_s, hit)`` for a constant-A pose or XYZ sweep.

        Point poses and sub-cell XYZ steps use an analytic solid-of-revolution
        test (V-bit / taper wrapping). Longer XYZ sweeps still binary-search.
        """
        uy, uz, y0, z0_axis = self._ray_frame(it, angle)
        z0 = float(profile_zs[0]) if profile_zs.size else 0.0
        z1 = float(profile_zs[-1]) if profile_zs.size else 0.0
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        seg_len_sq = dx * dx + dy * dy + dz * dz
        cell = float(self.cell_size)
        if seg_len_sq <= cell * cell:
            tip = p0 if seg_len_sq < 1e-18 else (p0[0] + 0.5 * dx, p0[1] + 0.5 * dy, p0[2] + 0.5 * dz)
            if const_r is not None:
                return _cylinder_cut_radius(wx, uy, uz, y0, z0_axis, tip, const_r, z0, z1, slab, cell * 0.5)
            return _revolution_cut_radius(wx, uy, uz, y0, z0_axis, tip, profile_zs, profile_rs, slab, cell * 0.5)

        def _inside(r_field: np.ndarray) -> np.ndarray:
            valid = r_field >= 0.0
            yy = y0 + r_field * uy[None, :]
            zz = z0_axis + r_field * uz[None, :]
            return valid & _xyz_inside_tool(wx[:, None], yy, zz, p0, p1, profile_zs, profile_rs, const_r, max_r)

        hit = _inside(slab)
        hit |= _inside(np.maximum(slab - self.cell_size * 0.5, 0.0))
        if not hit.any():
            return slab, hit
        lo = np.zeros_like(slab)
        hi = slab.copy()
        for _ in range(self._radius_search_iters()):
            mid = 0.5 * (lo + hi)
            ins = _inside(mid)
            hi = np.where(ins, mid, hi)
            lo = np.where(ins, lo, mid)
        return np.maximum(lo, 0.0), hit

    def _carve_full_revolution(
        self,
        tip: tuple[float, float, float],
        angle: float,
        profile_zs: np.ndarray,
        profile_rs: np.ndarray,
        const_r: float | None,
        max_r: float,
    ) -> set[TileKey]:
        """Constant-XYZ wrap of ≥360°: one pose, then the same remaining r on every θ."""
        pad = max_r + self.cell_size
        ix0 = max(0, self._x_index(tip[0] - pad))
        ix1 = min(self.nx - 1, self._x_index(tip[0] + pad))
        if ix0 > ix1:
            return set()
        it = self._theta_window_indices(tip, tip, angle, max_r)
        if it.size == 0:
            return set()
        wx = self.bounds.min_x + (np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5) * self.cell_size
        ix = np.arange(ix0, ix1 + 1)
        slab = self.radii[ix[:, None], it[None, :]].astype(np.float64, copy=True)
        new_s, hit = self._cut_slab(slab, wx, it, angle, tip, tip, profile_zs, profile_rs, const_r, max_r)
        if not hit.any():
            return set()
        r_cut_x = np.min(np.where(hit, new_s, _INF), axis=1)
        ring = self.radii[ix0 : ix1 + 1, :].astype(np.float64, copy=True)
        upd = r_cut_x[:, None] < ring - 1e-9
        if not upd.any():
            return set()
        self.radii[ix0 : ix1 + 1, :] = np.where(upd, r_cut_x[:, None], ring).astype(np.float32)
        self._clear_laser_indexed(ix0, np.arange(self.n_theta, dtype=np.int32), upd)
        dirty = self._dirty_from_mask(upd, ix0, np.arange(self.n_theta, dtype=np.int32))
        self._touched |= dirty
        return dirty

    def _carve_moving_a(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        a0: float,
        a1: float,
        profile_zs: np.ndarray,
        profile_rs: np.ndarray,
        const_r: float | None,
        max_r: float,
    ) -> set[TileKey]:
        """Wrapping / helix: sample poses, cut into one buffer, commit once."""
        da = a1 - a0
        tseg = pose_ts_cell_aligned(
            p0,
            p1,
            a0,
            a1,
            min_x=self.bounds.min_x,
            cell_size_mm=self.cell_size,
            d_theta_deg=self.d_theta,
        )
        pad = max_r + self.cell_size
        ix0 = max(0, self._x_index(min(p0[0], p1[0]) - pad))
        ix1 = min(self.nx - 1, self._x_index(max(p0[0], p1[0]) + pad))
        if ix0 > ix1:
            return set()
        wx_all = self.bounds.min_x + (np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5) * self.cell_size
        r_work = self.radii[ix0 : ix1 + 1, :].astype(np.float64, copy=True)
        changed = np.zeros(r_work.shape, dtype=bool)
        dxs, dys, dzs = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        for t in tseg:
            tt = float(t)
            tip = (p0[0] + tt * dxs, p0[1] + tt * dys, p0[2] + tt * dzs)
            ang = a0 + tt * da
            it = self._theta_window_indices(tip, tip, ang, max_r)
            if it.size == 0:
                continue
            j0 = max(0, self._x_index(tip[0] - pad) - ix0)
            j1 = min(r_work.shape[0] - 1, self._x_index(tip[0] + pad) - ix0)
            if j0 > j1:
                continue
            wx = wx_all[j0 : j1 + 1]
            slab = r_work[j0 : j1 + 1, it]
            new_s, hit = self._cut_slab(slab, wx, it, ang, tip, tip, profile_zs, profile_rs, const_r, max_r)
            upd = hit & (new_s < slab - 1e-9)
            if not upd.any():
                continue
            r_work[j0 : j1 + 1, it] = np.where(upd, new_s, slab)
            changed[j0 : j1 + 1, it] |= upd
        if not changed.any():
            return set()
        self.radii[ix0 : ix1 + 1, :] = r_work.astype(np.float32)
        self._clear_laser_indexed(ix0, np.arange(self.n_theta, dtype=np.int32), changed)
        dirty = self._dirty_from_mask(changed, ix0, np.arange(self.n_theta, dtype=np.int32))
        self._touched |= dirty
        return dirty

    def _carve_constant_a(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        angle: float,
        profile_zs: np.ndarray,
        profile_rs: np.ndarray,
        const_r: float | None,
        max_r: float,
    ) -> set[TileKey]:
        pad = max_r + self.cell_size
        x_lo = min(p0[0], p1[0]) - pad
        x_hi = max(p0[0], p1[0]) + pad
        ix0 = max(0, self._x_index(x_lo))
        ix1 = min(self.nx - 1, self._x_index(x_hi))
        if ix0 > ix1:
            return set()
        it = self._theta_window_indices(p0, p1, angle, max_r)
        if it.size == 0:
            return set()
        wx = self.bounds.min_x + (np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5) * self.cell_size
        ix = np.arange(ix0, ix1 + 1)
        slab = self.radii[ix[:, None], it[None, :]].astype(np.float64, copy=True)
        new_s, hit = self._cut_slab(slab, wx, it, angle, p0, p1, profile_zs, profile_rs, const_r, max_r)
        upd = hit & (new_s < slab - 1e-9)
        return self._write_slab(ix0, it, np.where(upd, new_s, slab), upd)

    def snapshot_full(self) -> object:
        return self._snapshot_with_laser(("full", compress_array(self.radii)), full=True)

    def snapshot_changed(self, keys: set[TileKey]) -> object:
        ts = self.tile_size
        tiles: dict[TileKey, np.ndarray] = {}
        for key in keys:
            tx, tt, _ = key
            x0, t0 = tx * ts, tt * ts
            x1, t1 = min(self.nx, x0 + ts), min(self.n_theta, t0 + ts)
            tiles[key] = self.radii[x0:x1, t0:t1].copy()
        return self._snapshot_with_laser(("delta", tiles), full=False)

    def restore(self, payload: object) -> set[TileKey]:
        occ, laser_payload = split_laser_snapshot(payload)
        kind, data = occ  # type: ignore[misc]
        if kind == "full":
            self.radii[:, :] = decompress_array(data)
            self._touched = self._tiles_not_at_seed()
            self._restore_laser_payload(laser_payload, occupancy_kind=kind)
            return self.initial_surface_keys()
        dirty: set[TileKey] = set()
        ts = self.tile_size
        for key, tile in data.items():
            tx, tt, _ = key
            x0, t0 = tx * ts, tt * ts
            x1, t1 = x0 + tile.shape[0], t0 + tile.shape[1]
            self.radii[x0:x1, t0:t1] = tile
            dirty.add(key)
        self._touched |= dirty
        self._restore_laser_payload(laser_payload, occupancy_kind=kind)
        return dirty

    def copy_tiles(self, keys: set[TileKey]) -> CylindricalBackend:
        ts = self.tile_size
        if not keys:
            return CylindricalBackend(
                self.bounds,
                self.cell_size,
                self.shape,
                self.tile_size,
                radii=np.empty((0, self.n_theta), dtype=np.float32),
                seed=False,
                index_origin_x=0,
                laser_cell_size_mm=self._laser_cell_size,
            )
        txs = [k[0] for k in keys]
        x0 = max(0, min(txs) * ts)
        x1 = min(self.nx, (max(txs) + 1) * ts)
        window = self.radii[x0 - self._ox : x1 - self._ox, :].copy() if self._ox else self.radii[x0:x1, :].copy()
        return CylindricalBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.tile_size,
            radii=window,
            seed=False,
            index_origin_x=x0,
            laser_cell_size_mm=self._laser_cell_size,
        )

    def expand_dirty(self, dirty: set[TileKey]) -> set[TileKey]:
        expanded = set(dirty)
        for tx, tt, _ in dirty:
            for dx in (-1, 0, 1):
                for dt in (-1, 0, 1):
                    x = tx + dx
                    t = (tt + dt) % self.n_tiles_theta
                    if 0 <= x < self.n_tiles_x:
                        expanded.add((x, t, 0))
        return expanded

    def initial_surface_keys(self) -> set[TileKey]:
        return {(tx, tt, 0) for tx in range(self.n_tiles_x) for tt in range(self.n_tiles_theta)}

    def all_non_full_keys(self) -> set[TileKey]:
        return set(self._touched)

    def _tiles_not_at_seed(self) -> set[TileKey]:
        if self.radii.shape != (self.nx, self.n_theta):
            return set(self._touched)
        seed = np.empty_like(self.radii)
        self._fill_seed(seed)
        mask = np.abs(self.radii - seed) > 1e-4
        return tile_keys_from_window_mask(mask, 0, 0, self.tile_size)

    def mesh_tiles(self, keys: set[TileKey]) -> dict[TileKey, tuple | None]:
        """Coalesced GPU meshes for the whole cylindrical shell (uint16-safe chunks)."""
        if not keys or self.radii.size == 0:
            return {(0, 0, 0): None} if keys else {}
        packed = _mesh_cylindrical_field(self)
        return keyed_packed_meshes(packed)

    def hud_stats(self) -> dict:
        return {
            "carver": self.kind,
            "cell_size_mm": float(self.cell_size),
            "grid_nx": int(self.nx),
            "grid_ny": int(self.n_theta),
            "grid_nz": 1,
            "stock_diameter_mm": float(self.stock_radius) * 2.0,
        }

    @staticmethod
    def create_checkpoint_store(slot_count: int):
        return ArrayCheckpointStore(slot_count=slot_count)

    @staticmethod
    def restore_checkpoint(store, checkpoint, backend) -> set:
        return restore_array_checkpoint(backend, store, checkpoint)

    def radius_at(self, x: float, angle_deg: float) -> float | None:
        ix = self._x_index(x)
        it = self._theta_index(angle_deg)
        if not (0 <= ix < self.nx):
            return None
        r = float(self._read_cell(ix, it))
        return None if r < 0 else r

    def is_solid_at_world(self, x: float, y: float, z: float) -> bool:
        """True if world point is inside remaining stock (axis-centered cylinder)."""
        ix = self._x_index(x)
        if not (0 <= ix < self.nx):
            return False
        dy = y - self.axis_y
        dz = z - self.axis_z
        r = math.hypot(dy, dz)
        ang = math.degrees(math.atan2(dy, dz)) % 360.0
        it = self._theta_index(ang)
        rem = float(self._read_cell(ix, it))
        if rem < 0:
            return False
        return r <= rem + 1e-6

    def _read_cell(self, ix: int, it: int) -> float:
        lx = ix - self._ox
        if lx < 0 or lx >= self.radii.shape[0] or it < 0 or it >= self.radii.shape[1]:
            return float(_EMPTY_R)
        return float(self.radii[lx, it])


def _mesh_cylindrical_field(backend: CylindricalBackend) -> list[tuple[list[float], list[int], list]]:
    """Regular (x, θ) grid — no greedy X-merge (that left T-junction holes on slopes)."""
    ox = backend._ox
    radii = backend.radii
    nx_win, n_theta = int(radii.shape[0]), int(radii.shape[1])
    if nx_win < 1 or n_theta < 1:
        return []

    ay, az = float(backend.axis_y), float(backend.axis_z)
    vs = float(backend.cell_size)
    wx0 = float(backend.bounds.min_x)
    sin_t = backend._sin_t.astype(np.float64, copy=False)
    cos_t = backend._cos_t.astype(np.float64, copy=False)
    gx0 = ox
    xs = wx0 + (np.arange(gx0, gx0 + nx_win, dtype=np.float64) + 0.5) * vs
    r_occ = radii.astype(np.float64, copy=False)
    floor = shell_floor_radius_mm(vs)
    # Occupancy may be r=0 (past the axis). Draw a hairline tube so the skin
    # stays closed without collapsing every θ onto the axis.
    r = np.where(r_occ >= 0.0, np.maximum(r_occ, floor), r_occ)

    parts_c: list[np.ndarray] = []
    parts_n: list[np.ndarray] = []

    if nx_win >= 2:
        pts = np.empty((nx_win, n_theta, 3), dtype=np.float32)
        pts[:, :, 0] = xs[:, None]
        pts[:, :, 1] = (ay + r * sin_t[None, :]).astype(np.float32)
        pts[:, :, 2] = (az + r * cos_t[None, :]).astype(np.float32)
        r0, r1 = r_occ[:-1], r_occ[1:]
        r0n = np.roll(r0, -1, axis=1)
        r1n = np.roll(r1, -1, axis=1)
        ok = (r0 >= 0.0) & (r1 >= 0.0) & (r0n >= 0.0) & (r1n >= 0.0)
        p00 = pts[:-1][ok]
        p10 = pts[1:][ok]
        p01 = np.roll(pts[:-1], -1, axis=1)[ok]
        p11 = np.roll(pts[1:], -1, axis=1)[ok]
        if p00.size:
            mid = 0.25 * (p00 + p10 + p11 + p01)
            hint = np.empty_like(mid)
            hint[:, 0] = 0.0
            hint[:, 1] = mid[:, 1] - ay
            hint[:, 2] = mid[:, 2] - az
            shell = pick_outward_quads(p00, p10, p11, p01, hint)
            parts_c.append(shell)
            parts_n.append(quad_normals(shell))

    def _cap(ix: int, x_sign: float) -> None:
        li = ix - ox
        if li < 0 or li >= nx_win:
            return
        ring = r[li]
        occ = r_occ[li]
        rn = np.roll(ring, -1)
        occ_n = np.roll(occ, -1)
        ok = (occ >= 0.0) & (occ_n >= 0.0)
        if not ok.any():
            return
        x = wx0 + (ix + 0.5) * vs
        p_it = np.stack((np.full(n_theta, x), ay + ring * sin_t, az + ring * cos_t), axis=1).astype(np.float32)
        p_n = np.stack(
            (np.full(n_theta, x), ay + rn * np.roll(sin_t, -1), az + rn * np.roll(cos_t, -1)),
            axis=1,
        ).astype(np.float32)
        center = np.array((x, ay, az), dtype=np.float32)
        ctr = np.broadcast_to(center, (n_theta, 3))
        if x_sign < 0.0:
            cap = np.stack((ctr, p_it, p_n, ctr), axis=1)
        else:
            cap = np.stack((ctr, p_n, p_it, ctr), axis=1)
        nrm = np.zeros((n_theta, 3), dtype=np.float32)
        nrm[:, 0] = x_sign
        parts_c.append(cap[ok])
        parts_n.append(nrm[ok])

    if gx0 <= 0:
        _cap(0, -1.0)
    if gx0 + nx_win >= backend.nx:
        _cap(backend.nx - 1, 1.0)

    if not parts_c:
        return []
    corners = np.concatenate(parts_c, axis=0)
    normals = np.concatenate(parts_n, axis=0)
    return pack_quad_meshes(corners, normals, DEFAULT_COLOR)
