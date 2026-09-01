"""Voxel occupancy carving from toolpath segments + tool profiles."""

from __future__ import annotations

import math

import numpy as np

from carveracontroller.addons.stock.stock_geometry import rotate_yz
from carveracontroller.addons.tool_visualization.mesh_builder import (
    effective_tool_diameter,
    fallback_tool_dimensions,
    profile_length,
    resolve_section_lengths,
    tool_profile,
)
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition

from .grid import CHUNK_EMPTY, CHUNK_FULL, ChunkedVoxelGrid

# Subdivide wrapping / helical A so each constant-A carve is a few degrees.
_MAX_DA_DEG = 2.0


def _max_profile_radius(profile: list[tuple[float, float]]) -> float:
    if not profile:
        return 0.0
    return max(r for _z, r in profile)


def _truncate_profile_to_cut(profile: list[tuple[float, float]], cut_z: float) -> list[tuple[float, float]]:
    """Keep only the cutting section of a tool profile (exclude shank)."""
    if not profile or cut_z <= 0:
        return profile
    out: list[tuple[float, float]] = []
    for z, r in profile:
        if z <= cut_z + 1e-9:
            out.append((z, r))
        else:
            break
    if not out:
        return profile[:2] if len(profile) >= 2 else profile
    if out[-1][0] < cut_z - 1e-9:
        out.append((cut_z, out[-1][1]))
    return out


def _resolve_profile(
    tool_def: ToolDefinition | None,
    tool_unit_scale: float = 1.0,
) -> list[tuple[float, float]]:
    """Cutting profile in mm (flute/shoulder only).

    Build/truncate in file units, then scale ``(z, r)`` by ``tool_unit_scale``.
    Do not pass that scale into :func:`tool_profile`. Null-tool fallback is mm.
    """
    if tool_def is None:
        diameter, length = fallback_tool_dimensions(1.0)
        return [(0.0, diameter / 2.0), (length, diameter / 2.0)]

    profile = list(tool_profile(tool_def, scale=1.0))
    diameter = effective_tool_diameter(tool_def, scale=1.0)
    fallback_overall = profile_length(tool_def, scale=1.0, diameter=diameter)
    flute_z, shoulder_z, _overall = resolve_section_lengths(tool_def, fallback_overall)
    cut_z = max(flute_z, shoulder_z)
    profile = _truncate_profile_to_cut(profile, cut_z)
    s = float(tool_unit_scale) if tool_unit_scale else 1.0
    if s != 1.0:
        profile = [(z * s, r * s) for z, r in profile]
    return profile


def _local_z_slab(oz: float, vs: float, cs: int, tip_z_lo: float, tip_z_hi: float) -> tuple[int, int]:
    """Local Z index range ``[iz_lo, iz_hi)`` whose centres may meet the cutter.

    Centres are ``oz + (iz + 0.5) * vs``. ``tip_z_lo`` / ``tip_z_hi`` already include
    a one-voxel pad; ``floor`` on both ends keeps every centre the un-slabbed dense
    path could have accepted.
    """
    if vs <= 0 or cs <= 0:
        return 0, max(0, cs)
    lo = (float(tip_z_lo) - float(oz)) / float(vs) - 0.5
    hi = (float(tip_z_hi) - float(oz)) / float(vs) - 0.5
    iz_lo = max(0, int(np.floor(lo)))
    iz_hi = min(cs, int(np.floor(hi)) + 1)
    return iz_lo, iz_hi


def _local_z_slab_rotated(
    oz: float,
    vs: float,
    cs: int,
    oy: float,
    cy1: float,
    angle_deg: float,
    tip_z_lo: float,
    tip_z_hi: float,
) -> tuple[int, int]:
    """Stock-Z slab whose machine-Z (after ``Rx(-A)``) can meet the cutter.

    Machine ``z = y * sin(-A) + z_stock * cos(-A)``. For a fixed stock-Z slice,
    machine Z extrema are at the chunk's Y endpoints — a conservative overlap
    test against ``[tip_z_lo, tip_z_hi]``.
    """
    if vs <= 0 or cs <= 0:
        return 0, max(0, cs)
    rad = np.deg2rad(-float(angle_deg))
    c = float(np.cos(rad))
    s = float(np.sin(rad))
    y_term_min = min(float(oy) * s, float(cy1) * s)
    y_term_max = max(float(oy) * s, float(cy1) * s)
    zs = float(oz) + (np.arange(cs, dtype=np.float64) + 0.5) * float(vs)
    mz_lo = zs * c + y_term_min
    mz_hi = zs * c + y_term_max
    hit = (mz_lo <= float(tip_z_hi)) & (mz_hi >= float(tip_z_lo))
    if not bool(hit.any()):
        return 0, 0
    iz = np.flatnonzero(hit)
    return int(iz[0]), int(iz[-1]) + 1


def _constant_profile_radius(profile_rs: np.ndarray) -> float | None:
    """Return the shared radius when every profile knot is the same, else ``None``."""
    if profile_rs.size == 0:
        return None
    rmin = float(np.min(profile_rs))
    rmax = float(np.max(profile_rs))
    if rmax - rmin < 1e-12:
        return rmax
    return None


def _aabb_rotated_around_x(
    aabb: tuple[float, float, float, float, float, float],
    angle_deg: float,
) -> tuple[float, float, float, float, float, float]:
    """Axis-aligned bounds of *aabb* after rotating YZ around X by *angle_deg*."""
    min_x, min_y, min_z, max_x, max_y, max_z = aabb
    ys: list[float] = []
    zs: list[float] = []
    for y in (min_y, max_y):
        for z in (min_z, max_z):
            y2, z2 = rotate_yz(y, z, angle_deg)
            ys.append(y2)
            zs.append(z2)
    return (min_x, min(ys), min(zs), max_x, max(ys), max(zs))


def _rotate_yz_np(yy: np.ndarray, zz: np.ndarray, angle_deg: float) -> tuple[np.ndarray, np.ndarray]:
    rad = np.deg2rad(float(angle_deg))
    c = np.cos(rad)
    s = np.sin(rad)
    return yy * c - zz * s, yy * s + zz * c


def carve_segment_into_grid(
    grid: ChunkedVoxelGrid,
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    tool_def: ToolDefinition | None,
    tool_unit_scale: float = 1.0,
    *,
    sparse_solid_frac: float = 0.5,
    a0: float = 0.0,
    a1: float = 0.0,
) -> set[tuple[int, int, int]]:
    """Carve one toolpath segment into ``grid``.

    Returns chunks whose occupancy changed. Remesh callers should expand with
    :func:`_expand_dirty_with_neighbors`. Tip follows ``p0→p1``; cutting body is
    the upright surface of revolution from :func:`tool_profile`. A voxel clears
    iff some tip pose on the segment contains it (Z-valid tip window + XY-closest
    tip, then profile radius). ``sparse_solid_frac`` selects the solid-only gather
    path (tests may force ``0.0`` / ``1.0``).

    ``a0`` / ``a1`` are A-axis angles in degrees at the segment ends. Non-zero
    A rotates the stock: voxels are tested in machine XYZ via ``Rx(-A)``.
    """
    a0 = float(a0)
    a1 = float(a1)
    da = a1 - a0
    if abs(da) > _MAX_DA_DEG:
        n = max(1, int(math.ceil(abs(da) / _MAX_DA_DEG)))
        dirty: set[tuple[int, int, int]] = set()
        dxs = p1[0] - p0[0]
        dys = p1[1] - p0[1]
        dzs = p1[2] - p0[2]
        for i in range(n):
            t0 = i / n
            t1 = (i + 1) / n
            pi0 = (p0[0] + t0 * dxs, p0[1] + t0 * dys, p0[2] + t0 * dzs)
            pi1 = (p0[0] + t1 * dxs, p0[1] + t1 * dys, p0[2] + t1 * dzs)
            ai = a0 + 0.5 * (t0 + t1) * da
            dirty |= carve_segment_into_grid(
                grid,
                pi0,
                pi1,
                tool_def,
                tool_unit_scale,
                sparse_solid_frac=sparse_solid_frac,
                a0=ai,
                a1=ai,
            )
        return dirty

    profile = _resolve_profile(tool_def, tool_unit_scale=tool_unit_scale)
    max_r = _max_profile_radius(profile)
    flute_z = profile[-1][0] if profile else 0.0
    if max_r <= 0 and flute_z <= 0:
        return set()

    profile_zs = np.array([z for z, _r in profile], dtype=np.float64) if profile else np.zeros(0)
    profile_rs = np.array([r for _z, r in profile], dtype=np.float64) if profile else np.zeros(0)
    const_r = _constant_profile_radius(profile_rs)

    xs = (p0[0], p1[0])
    ys = (p0[1], p1[1])
    zs = (p0[2], p1[2])
    pad = max_r + grid.voxel_size
    aabb = (
        min(xs) - pad,
        min(ys) - pad,
        min(zs) - pad,
        max(xs) + pad,
        max(ys) + pad,
        max(zs) + flute_z + pad,
    )
    angle = a0
    rotate = abs(angle) > 1e-9
    if rotate:
        aabb = _aabb_rotated_around_x(aabb, angle)

    dirty: set[tuple[int, int, int]] = set()
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    dz = p1[2] - p0[2]
    seg_len_sq = dx * dx + dy * dy + dz * dz
    xy_len_sq = dx * dx + dy * dy
    z0 = float(profile[0][0]) if profile else 0.0
    z1 = float(profile[-1][0]) if profile else 0.0
    eps = 1e-9
    vs = grid.voxel_size
    tip_z_lo = min(p0[2], p1[2]) - vs
    tip_z_hi = max(p0[2], p1[2]) + flute_z + vs
    xy_reject_r = max_r + vs

    for coord in grid.iter_chunks_in_aabb(*aabb):
        state = grid.get_chunk_state(coord)
        if state is CHUNK_EMPTY:
            continue

        cs = grid.chunk_size
        ox, oy, oz = grid.chunk_world_origin(coord)
        cx1 = ox + cs * vs
        cy1 = oy + cs * vs
        cz1 = oz + cs * vs

        if rotate:
            # Chunk AABB in machine XYZ (voxels are tested via Rx(-A)).
            mx0, my0, mz0, mx1, my1, mz1 = _aabb_rotated_around_x((ox, oy, oz, cx1, cy1, cz1), -angle)
            if mz1 < tip_z_lo or mz0 > tip_z_hi:
                continue
            if _segment_aabb_dist_xy(p0[0], p0[1], p1[0], p1[1], mx0, my0, mx1, my1) > xy_reject_r:
                continue
        else:
            if cz1 < tip_z_lo or oz > tip_z_hi:
                continue
            if _segment_aabb_dist_xy(p0[0], p0[1], p1[0], p1[1], ox, oy, cx1, cy1) > xy_reject_r:
                continue

        was_full = state is CHUNK_FULL
        arr = grid.get_or_create_chunk(coord)
        if arr is None:
            continue

        if was_full:
            solid_count = grid._valid_count(coord)
        else:
            solid_count = int(arr.sum())
        if solid_count == 0:
            grid.maybe_collapse_chunk(coord, arr, solid_count=0)
            continue

        chunk_voxels = cs * cs * cs
        use_sparse = solid_count <= chunk_voxels * sparse_solid_frac
        valid = grid._valid_mask(coord)
        if rotate:
            z_lo, z_hi = _local_z_slab_rotated(oz, vs, cs, oy, cy1, angle, tip_z_lo, tip_z_hi)
        else:
            z_lo, z_hi = _local_z_slab(oz, vs, cs, tip_z_lo, tip_z_hi)

        if use_sparse:
            ixs, iys, izs = np.nonzero(arr)
            if z_lo > 0 or z_hi < cs:
                keep = (izs >= z_lo) & (izs < z_hi)
                ixs, iys, izs = ixs[keep], iys[keep], izs[keep]
            if ixs.size == 0:
                if was_full:
                    grid.release_unmodified_full(coord)
                continue
            XX = ox + (ixs.astype(np.float64) + 0.5) * vs
            YY = oy + (iys.astype(np.float64) + 0.5) * vs
            ZZ = oz + (izs.astype(np.float64) + 0.5) * vs
            if rotate:
                YY, ZZ = _rotate_yz_np(YY, ZZ, -angle)
            inside = _voxels_inside_tool(
                XX,
                YY,
                ZZ,
                p0,
                dx,
                dy,
                dz,
                seg_len_sq,
                xy_len_sq,
                z0,
                z1,
                profile,
                profile_zs,
                profile_rs,
                eps,
                max_r,
                const_r,
            )
            inside &= valid[ixs, iys, izs]
            if not inside.any():
                if was_full:
                    grid.release_unmodified_full(coord)
                continue
            n_hit = int(np.count_nonzero(inside))
            arr[ixs[inside], iys[inside], izs[inside]] = 0
            after = solid_count - n_hit
        else:
            if z_lo >= z_hi:
                if was_full:
                    grid.release_unmodified_full(coord)
                continue
            lx = ox + (np.arange(cs, dtype=np.float64) + 0.5) * vs
            ly = oy + (np.arange(cs, dtype=np.float64) + 0.5) * vs
            lz = oz + (np.arange(z_lo, z_hi, dtype=np.float64) + 0.5) * vs
            XX = lx[:, None, None]
            YY = ly[None, :, None]
            ZZ = lz[None, None, :]
            if rotate:
                YY, ZZ = _rotate_yz_np(YY, ZZ, -angle)
            inside = _voxels_inside_tool(
                XX,
                YY,
                ZZ,
                p0,
                dx,
                dy,
                dz,
                seg_len_sq,
                xy_len_sq,
                z0,
                z1,
                profile,
                profile_zs,
                profile_rs,
                eps,
                max_r,
                const_r,
            )
            slab = arr[:, :, z_lo:z_hi]
            inside &= valid[:, :, z_lo:z_hi] & slab.astype(bool)
            if not inside.any():
                if was_full:
                    grid.release_unmodified_full(coord)
                continue
            n_hit = int(np.count_nonzero(inside))
            slab[inside] = 0
            after = solid_count - n_hit

        grid.maybe_collapse_chunk(coord, arr, solid_count=after)
        if after != solid_count:
            dirty.add(coord.as_tuple())

    return dirty


def _voxels_inside_tool(
    XX: np.ndarray,
    YY: np.ndarray,
    ZZ: np.ndarray,
    p0: tuple[float, float, float],
    dx: float,
    dy: float,
    dz: float,
    seg_len_sq: float,
    xy_len_sq: float,
    z0: float,
    z1: float,
    profile: list[tuple[float, float]],
    profile_zs: np.ndarray,
    profile_rs: np.ndarray,
    eps: float,
    max_r: float,
    const_r: float | None | object = ...,
) -> np.ndarray:
    """Shared tip-window / radius mask for dense or sparse coordinate layouts.

    ``max_r`` is the profile peak; centres farther than that in XY are rejected
    before radius interpolation. A constant-radius profile (flat mill) skips
    ``searchsorted`` entirely. ``const_r`` defaults to ``...`` meaning "compute
    from ``profile_rs``" so tests can patch :func:`_constant_profile_radius`.
    """
    XX = np.asarray(XX, dtype=np.float64)
    YY = np.asarray(YY, dtype=np.float64)
    ZZ = np.asarray(ZZ, dtype=np.float64)
    if const_r is ...:
        const_r = _constant_profile_radius(profile_rs)

    def _inside_from_xy(
        window_ok: np.ndarray,
        dist_xy: np.ndarray,
        *,
        z_rel: np.ndarray | None = None,
        band_lo: np.ndarray | None = None,
        band_hi: np.ndarray | None = None,
    ) -> np.ndarray:
        candidate = window_ok & (dist_xy <= max_r + eps)
        if not candidate.any():
            return candidate
        if const_r is not None:
            return candidate if const_r > 0 else np.zeros(candidate.shape, dtype=bool)
        radii = np.zeros(candidate.shape, dtype=np.float64)
        if band_lo is not None and band_hi is not None:
            lo_b, hi_b, cand_b = np.broadcast_arrays(band_lo, band_hi, candidate)
            radii[cand_b] = _max_profile_radii_in_band(
                profile, lo_b[cand_b], hi_b[cand_b], zs=profile_zs, rs=profile_rs
            )
            dist_b = np.broadcast_to(dist_xy, cand_b.shape)
            return cand_b & (dist_b <= radii + eps) & (radii > 0)
        if z_rel is None:
            return np.zeros(candidate.shape, dtype=bool)
        z_b, cand_b = np.broadcast_arrays(z_rel, candidate)
        radii[cand_b] = _sample_profile_radii(profile, z_b[cand_b], zs=profile_zs, rs=profile_rs)
        dist_b = np.broadcast_to(dist_xy, cand_b.shape)
        return cand_b & (dist_b <= radii + eps) & (radii > 0)

    if seg_len_sq < 1e-18:
        z_rel = ZZ - p0[2]
        dist_xy = np.sqrt((XX - p0[0]) ** 2 + (YY - p0[1]) ** 2)
        if profile_zs.size:
            window_ok = (z_rel >= profile_zs[0] - 1e-9) & (z_rel <= profile_zs[-1] + 1e-9)
        else:
            window_ok = np.zeros(ZZ.shape, dtype=bool)
        return _inside_from_xy(window_ok, dist_xy, z_rel=z_rel)

    if xy_len_sq < 1e-18:
        # Pure plunge — clear if within max radius over the z_rel band.
        tip_z_lo = min(p0[2], p0[2] + dz)
        tip_z_hi = max(p0[2], p0[2] + dz)
        z_rel_lo = ZZ - tip_z_hi
        z_rel_hi = ZZ - tip_z_lo
        band_lo = np.maximum(z_rel_lo, z0)
        band_hi = np.minimum(z_rel_hi, z1)
        window_ok = band_lo <= band_hi + eps
        dist_xy = np.sqrt((XX - p0[0]) ** 2 + (YY - p0[1]) ** 2)
        return _inside_from_xy(window_ok, dist_xy, band_lo=band_lo, band_hi=band_hi)

    # XY motion: Z-valid tip window, then XY-closest tip in that window.
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
    dist_xy = np.sqrt((XX - tip_x) ** 2 + (YY - tip_y) ** 2)
    return _inside_from_xy(window_ok, dist_xy, z_rel=z_rel)


def _segments_intersect_2d(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
) -> bool:
    """True if closed segments AB and CD intersect (including touching)."""

    def _orient(px, py, qx, qy, rx, ry) -> float:
        return (qy - py) * (rx - qx) - (qx - px) * (ry - qy)

    def _on_seg(px, py, qx, qy, rx, ry) -> bool:
        return min(px, rx) - 1e-12 <= qx <= max(px, rx) + 1e-12 and min(py, ry) - 1e-12 <= qy <= max(py, ry) + 1e-12

    o1 = _orient(ax, ay, bx, by, cx, cy)
    o2 = _orient(ax, ay, bx, by, dx, dy)
    o3 = _orient(cx, cy, dx, dy, ax, ay)
    o4 = _orient(cx, cy, dx, dy, bx, by)

    if (o1 > 0 and o2 < 0 or o1 < 0 and o2 > 0) and (o3 > 0 and o4 < 0 or o3 < 0 and o4 > 0):
        return True
    if abs(o1) <= 1e-12 and _on_seg(ax, ay, cx, cy, bx, by):
        return True
    if abs(o2) <= 1e-12 and _on_seg(ax, ay, dx, dy, bx, by):
        return True
    if abs(o3) <= 1e-12 and _on_seg(cx, cy, ax, ay, dx, dy):
        return True
    return abs(o4) <= 1e-12 and _on_seg(cx, cy, bx, by, dx, dy)


def _segment_aabb_dist_xy(
    ax: float,
    ay: float,
    bx: float,
    by: float,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> float:
    """Minimum 2D distance from tip segment AB to an axis-aligned rectangle."""

    def _inside(px: float, py: float) -> bool:
        return xmin <= px <= xmax and ymin <= py <= ymax

    if _inside(ax, ay) or _inside(bx, by):
        return 0.0

    edges = (
        (xmin, ymin, xmax, ymin),
        (xmax, ymin, xmax, ymax),
        (xmax, ymax, xmin, ymax),
        (xmin, ymax, xmin, ymin),
    )
    for ex0, ey0, ex1, ey1 in edges:
        if _segments_intersect_2d(ax, ay, bx, by, ex0, ey0, ex1, ey1):
            return 0.0

    def _point_to_aabb(px: float, py: float) -> float:
        cx = min(max(px, xmin), xmax)
        cy = min(max(py, ymin), ymax)
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def _point_to_seg(px: float, py: float) -> float:
        abx = bx - ax
        aby = by - ay
        ab_len_sq = abx * abx + aby * aby
        if ab_len_sq < 1e-18:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = ((px - ax) * abx + (py - ay) * aby) / ab_len_sq
        t = max(0.0, min(1.0, t))
        qx = ax + t * abx
        qy = ay + t * aby
        return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5

    d = min(_point_to_aabb(ax, ay), _point_to_aabb(bx, by))
    for cx, cy in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)):
        d = min(d, _point_to_seg(cx, cy))
    return float(d)


def _max_profile_radii_in_band(
    profile: list[tuple[float, float]],
    band_lo: np.ndarray,
    band_hi: np.ndarray,
    *,
    zs: np.ndarray | None = None,
    rs: np.ndarray | None = None,
) -> np.ndarray:
    """Max profile radius over each voxel's achievable ``[band_lo, band_hi]``."""
    # Endpoints cover flat mills exactly; for ball/V, also sample interior knots.
    r_lo = _sample_profile_radii(profile, band_lo, zs=zs, rs=rs)
    r_hi = _sample_profile_radii(profile, band_hi, zs=zs, rs=rs)
    out = np.maximum(r_lo, r_hi)
    if len(profile) <= 2:
        return out
    knot_zs = zs[1:-1] if zs is not None and len(zs) == len(profile) else None
    if knot_zs is None:
        knot_iter = (float(z) for z, _r in profile[1:-1])
    else:
        knot_iter = (float(z) for z in knot_zs)
    for z in knot_iter:
        z_arr = np.full_like(band_lo, z)
        in_band = (z_arr >= band_lo - 1e-9) & (z_arr <= band_hi + 1e-9)
        if not in_band.any():
            continue
        r_knot = _sample_profile_radii(profile, z_arr, zs=zs, rs=rs)
        out = np.where(in_band, np.maximum(out, r_knot), out)
    return out


def _sample_profile_radii(
    profile: list[tuple[float, float]],
    z_rel: np.ndarray,
    *,
    zs: np.ndarray | None = None,
    rs: np.ndarray | None = None,
) -> np.ndarray:
    """Vectorized profile radius lookup for an array of tool-relative Z values."""
    if not profile:
        return np.zeros_like(z_rel, dtype=np.float64)

    if zs is None or rs is None:
        zs = np.array([z for z, _r in profile], dtype=np.float64)
        rs = np.array([r for _z, r in profile], dtype=np.float64)

    flat = z_rel.ravel()
    out = np.zeros_like(flat, dtype=np.float64)

    # Below tip or above stick-out → 0
    below = flat < zs[0] - 1e-9
    above = flat > zs[-1] + 1e-9
    mid = ~(below | above)

    if mid.any():
        idx = np.searchsorted(zs, flat[mid], side="right") - 1
        idx = np.clip(idx, 0, len(zs) - 2)
        z0 = zs[idx]
        z1 = zs[idx + 1]
        r0 = rs[idx]
        r1 = rs[idx + 1]
        denom = z1 - z0
        t = np.zeros_like(flat[mid], dtype=np.float64)
        nonzero = np.abs(denom) >= 1e-12
        if nonzero.any():
            t[nonzero] = (flat[mid][nonzero] - z0[nonzero]) / denom[nonzero]
        out[mid] = r0 + t * (r1 - r0)

    return out.reshape(z_rel.shape)
