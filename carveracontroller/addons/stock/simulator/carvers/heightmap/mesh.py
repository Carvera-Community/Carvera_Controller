"""Heightmap meshing: greedy coplanar merge, then vectorized skirt/top packing."""

from __future__ import annotations

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.array_mesh import pack_quad_meshes
from carveracontroller.addons.stock.simulator.mesh_format import DEFAULT_COLOR

# Occupancy sentinel shared with HeightmapBackend (imported from this module).
_OUTSIDE = np.float32(-1e30)
_MERGE_Z = 1e-4
# Flat pockets/walls merge well; mixed ball-nose tiles do not (use vectorized quads).
_GREEDY_MIN_MERGE_FRAC = 0.6


def _as_xyz(x, y, z) -> np.ndarray:
    return np.stack(
        (
            np.asarray(x, dtype=np.float32),
            np.asarray(y, dtype=np.float32),
            np.asarray(z, dtype=np.float32),
        ),
        axis=-1,
    )


def _quads(c0: np.ndarray, c1: np.ndarray, c2: np.ndarray, c3: np.ndarray) -> np.ndarray:
    return np.stack((c0, c1, c2, c3), axis=1)


def _axis_normals(count: int, axis: int, sign: float) -> np.ndarray:
    nrm = np.zeros((count, 3), dtype=np.float32)
    if count:
        nrm[:, axis] = sign
    return nrm


def _empty_quads() -> np.ndarray:
    return np.empty((0, 4, 3), dtype=np.float32)


def _cell_xy(
    ii: np.ndarray, jj: np.ndarray, ox: float, oy: float, x0: int, y0: int, vs: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    wx0 = np.float32(ox) + (np.int32(x0) + ii) * np.float32(vs)
    wy0 = np.float32(oy) + (np.int32(y0) + jj) * np.float32(vs)
    vs32 = np.float32(vs)
    return wx0.astype(np.float32), wy0.astype(np.float32), wx0 + vs32, wy0 + vs32


def _top_quads(mask: np.ndarray, heights: np.ndarray, ox: float, oy: float, x0: int, y0: int, vs: float) -> np.ndarray:
    ii, jj = np.nonzero(mask)
    if ii.size == 0:
        return _empty_quads()
    wx0, wy0, wx1, wy1 = _cell_xy(ii, jj, ox, oy, x0, y0, vs)
    h = heights[ii, jj]
    return _quads(_as_xyz(wx0, wy0, h), _as_xyz(wx1, wy0, h), _as_xyz(wx1, wy1, h), _as_xyz(wx0, wy1, h))


def _skirt_quads(
    mask: np.ndarray,
    heights: np.ndarray,
    z_lo: np.ndarray,
    ox: float,
    oy: float,
    x0: int,
    y0: int,
    vs: float,
    side: str,
) -> np.ndarray:
    ii, jj = np.nonzero(mask)
    if ii.size == 0:
        return _empty_quads()
    wx0, wy0, wx1, wy1 = _cell_xy(ii, jj, ox, oy, x0, y0, vs)
    h = heights[ii, jj]
    lo = z_lo[ii, jj]
    if side == "left":
        return _quads(_as_xyz(wx0, wy0, h), _as_xyz(wx0, wy1, h), _as_xyz(wx0, wy1, lo), _as_xyz(wx0, wy0, lo))
    if side == "right":
        return _quads(_as_xyz(wx1, wy1, h), _as_xyz(wx1, wy0, h), _as_xyz(wx1, wy0, lo), _as_xyz(wx1, wy1, lo))
    if side == "down":
        return _quads(_as_xyz(wx1, wy0, h), _as_xyz(wx0, wy0, h), _as_xyz(wx0, wy0, lo), _as_xyz(wx1, wy0, lo))
    return _quads(_as_xyz(wx0, wy1, h), _as_xyz(wx1, wy1, h), _as_xyz(wx1, wy1, lo), _as_xyz(wx0, wy1, lo))


def _neighbor_merge_frac(valid: np.ndarray, heights: np.ndarray) -> float:
    """Fraction of adjacent valid pairs whose Z matches (greedy is worth it)."""
    n = 0
    same = 0
    if valid.shape[0] > 1:
        pair = valid[1:, :] & valid[:-1, :]
        n += int(pair.sum())
        same += int((pair & (np.abs(heights[1:, :] - heights[:-1, :]) <= _MERGE_Z)).sum())
    if valid.shape[1] > 1:
        pair = valid[:, 1:] & valid[:, :-1]
        n += int(pair.sum())
        same += int((pair & (np.abs(heights[:, 1:] - heights[:, :-1]) <= _MERGE_Z)).sum())
    if n == 0:
        return 0.0
    return same / n


def _rect_xy(
    i0: np.ndarray,
    j0: np.ndarray,
    i1: np.ndarray,
    j1: np.ndarray,
    ox: float,
    oy: float,
    x0: int,
    y0: int,
    vs: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    vs32 = np.float32(vs)
    wx0 = np.float32(ox) + (np.int32(x0) + i0) * vs32
    wy0 = np.float32(oy) + (np.int32(y0) + j0) * vs32
    wx1 = np.float32(ox) + (np.int32(x0) + i1) * vs32
    wy1 = np.float32(oy) + (np.int32(y0) + j1) * vs32
    return wx0.astype(np.float32), wy0.astype(np.float32), wx1.astype(np.float32), wy1.astype(np.float32)


def _greedy_flat_quads(
    mask: np.ndarray,
    heights: np.ndarray | None,
    ox: float,
    oy: float,
    x0: int,
    y0: int,
    vs: float,
    *,
    z_const: float | None = None,
    reverse_winding: bool = False,
) -> np.ndarray:
    """Merge axis-aligned runs of equal-Z masked cells into quads."""
    rows, cols = mask.shape
    if rows == 0 or cols == 0 or not mask.any():
        return _empty_quads()
    used = np.empty((rows, cols), dtype=bool)
    np.logical_not(mask, out=used)
    i_runs: list[int] = []
    j_runs: list[int] = []
    di_runs: list[int] = []
    dj_runs: list[int] = []
    z_runs: list[float] = []
    for i in range(rows):
        j = 0
        while j < cols:
            if used[i, j]:
                j += 1
                continue
            if z_const is not None:
                h = float(z_const)
            else:
                assert heights is not None
                h = float(heights[i, j])
            w = 1
            while j + w < cols and not used[i, j + w]:
                if z_const is None:
                    assert heights is not None
                    hh = float(heights[i, j + w])
                else:
                    hh = h
                if abs(hh - h) > _MERGE_Z:
                    break
                w += 1
            d = 1
            while i + d < rows:
                strip = used[i + d, j : j + w]
                if strip.any():
                    break
                if z_const is None:
                    assert heights is not None
                    if np.any(np.abs(heights[i + d, j : j + w] - h) > _MERGE_Z):
                        break
                d += 1
            used[i : i + d, j : j + w] = True
            i_runs.append(i)
            j_runs.append(j)
            di_runs.append(d)
            dj_runs.append(w)
            z_runs.append(h)
            j += w
    if not i_runs:
        return _empty_quads()
    i0 = np.asarray(i_runs, dtype=np.int32)
    j0 = np.asarray(j_runs, dtype=np.int32)
    i1 = i0 + np.asarray(di_runs, dtype=np.int32)
    j1 = j0 + np.asarray(dj_runs, dtype=np.int32)
    wx0, wy0, wx1, wy1 = _rect_xy(i0, j0, i1, j1, ox, oy, x0, y0, vs)
    zz = np.asarray(z_runs, dtype=np.float32)
    if reverse_winding:
        return _quads(_as_xyz(wx0, wy0, zz), _as_xyz(wx0, wy1, zz), _as_xyz(wx1, wy1, zz), _as_xyz(wx1, wy0, zz))
    return _quads(_as_xyz(wx0, wy0, zz), _as_xyz(wx1, wy0, zz), _as_xyz(wx1, wy1, zz), _as_xyz(wx0, wy1, zz))


def _merged_skirt_quads(
    mask: np.ndarray,
    heights: np.ndarray,
    z_lo: np.ndarray,
    ox: float,
    oy: float,
    x0: int,
    y0: int,
    vs: float,
    side: str,
) -> np.ndarray:
    """Merge consecutive same-height / same-floor skirt cells along the wall."""
    ii, jj = np.nonzero(mask)
    if ii.size == 0:
        return _empty_quads()
    h = heights[ii, jj]
    lo = z_lo[ii, jj]
    along_j = side in ("left", "right")
    order = np.lexsort((jj, ii)) if along_j else np.lexsort((ii, jj))
    ii = ii[order]
    jj = jj[order]
    h = h[order]
    lo = lo[order]
    i0s: list[int] = []
    j0s: list[int] = []
    i1s: list[int] = []
    j1s: list[int] = []
    hs: list[float] = []
    los: list[float] = []
    start = 0
    n = int(ii.size)
    for k in range(1, n + 1):
        prev = k - 1
        cont = False
        if k < n:
            if along_j:
                cont = (
                    ii[k] == ii[prev]
                    and jj[k] == jj[prev] + 1
                    and abs(float(h[k]) - float(h[prev])) <= _MERGE_Z
                    and abs(float(lo[k]) - float(lo[prev])) <= _MERGE_Z
                )
            else:
                cont = (
                    jj[k] == jj[prev]
                    and ii[k] == ii[prev] + 1
                    and abs(float(h[k]) - float(h[prev])) <= _MERGE_Z
                    and abs(float(lo[k]) - float(lo[prev])) <= _MERGE_Z
                )
        if cont:
            continue
        i0s.append(int(ii[start]))
        j0s.append(int(jj[start]))
        i1s.append(int(ii[prev]) + 1)
        j1s.append(int(jj[prev]) + 1)
        hs.append(float(h[start]))
        los.append(float(lo[start]))
        start = k
    i0 = np.asarray(i0s, dtype=np.int32)
    j0 = np.asarray(j0s, dtype=np.int32)
    i1 = np.asarray(i1s, dtype=np.int32)
    j1 = np.asarray(j1s, dtype=np.int32)
    hh = np.asarray(hs, dtype=np.float32)
    ll = np.asarray(los, dtype=np.float32)
    wx0, wy0, wx1, wy1 = _rect_xy(i0, j0, i1, j1, ox, oy, x0, y0, vs)
    if side == "left":
        return _quads(_as_xyz(wx0, wy0, hh), _as_xyz(wx0, wy1, hh), _as_xyz(wx0, wy1, ll), _as_xyz(wx0, wy0, ll))
    if side == "right":
        return _quads(_as_xyz(wx1, wy1, hh), _as_xyz(wx1, wy0, hh), _as_xyz(wx1, wy0, ll), _as_xyz(wx1, wy1, ll))
    if side == "down":
        return _quads(_as_xyz(wx1, wy0, hh), _as_xyz(wx0, wy0, hh), _as_xyz(wx0, wy0, ll), _as_xyz(wx1, wy0, ll))
    return _quads(_as_xyz(wx0, wy1, hh), _as_xyz(wx1, wy1, hh), _as_xyz(wx1, wy1, ll), _as_xyz(wx0, wy1, ll))


def mesh_heightmap_region(backend, x0: int, y0: int, x1: int, y1: int):
    """Build Kivy quad meshes for cells ``[x0:x1, y0:y1]``."""
    if x0 >= x1 or y0 >= y1:
        return []

    patch = backend._read_patch(x0 - 1, y0 - 1, x1 + 1, y1 + 1)
    core = patch[1:-1, 1:-1]
    bottom = float(backend.bounds.min_z)
    # Through-cuts clamp remaining Z to min_z. A zero-thickness cell is empty:
    # keeping a +Z quad there shows leftover stock from above, while back-face
    # culling hides it from below (no bottom faces are emitted either).
    valid = (core > _OUTSIDE * 0.5) & (core > bottom + _MERGE_Z)
    if not valid.any():
        return []
    vs = float(backend.cell_size)
    ox = float(backend.bounds.min_x)
    oy = float(backend.bounds.min_y)
    nx, ny = backend.nx, backend.ny
    rows, cols = core.shape

    n_left = patch[0:-2, 1:-1]
    n_right = patch[2:, 1:-1]
    n_down = patch[1:-1, 0:-2]
    n_up = patch[1:-1, 2:]
    ix = (x0 + np.arange(rows, dtype=np.int32))[:, None]
    iy = y0 + np.arange(cols, dtype=np.int32)

    def _skirt_mask(neigh: np.ndarray) -> np.ndarray:
        n_valid = neigh > _OUTSIDE * 0.5
        return valid & ((~n_valid) | (neigh < core - 1e-6))

    left_mask = _skirt_mask(n_left)
    right_mask = _skirt_mask(n_right)
    down_mask = _skirt_mask(n_down)
    up_mask = _skirt_mask(n_up)

    z_lo_left = np.where((ix == 0) | (n_left < _OUTSIDE * 0.5), bottom, n_left)
    z_lo_right = np.where((ix + 1 >= nx) | (n_right < _OUTSIDE * 0.5), bottom, n_right)
    z_lo_down = np.where((iy == 0) | (n_down < _OUTSIDE * 0.5), bottom, n_down)
    z_lo_up = np.where((iy + 1 >= ny) | (n_up < _OUTSIDE * 0.5), bottom, n_up)

    parts_c: list[np.ndarray] = []
    parts_n: list[np.ndarray] = []

    def _add(corners: np.ndarray, normals: np.ndarray) -> None:
        if corners.size:
            parts_c.append(corners)
            parts_n.append(normals)

    def _add_skirts(*, merge: bool) -> None:
        for mask, z_lo, side, axis, sign in (
            (left_mask, z_lo_left, "left", 0, -1.0),
            (right_mask, z_lo_right, "right", 0, 1.0),
            (down_mask, z_lo_down, "down", 1, -1.0),
            (up_mask, z_lo_up, "up", 1, 1.0),
        ):
            if merge:
                quads = _merged_skirt_quads(mask, core, z_lo, ox, oy, x0, y0, vs, side)
            else:
                quads = _skirt_quads(mask, core, z_lo, ox, oy, x0, y0, vs, side)
            _add(quads, _axis_normals(quads.shape[0], axis, sign))

    # Uniform tile: one top, one bottom, neighbor-aware skirts (still vectorized).
    if valid.all() and float(np.ptp(core)) < _MERGE_Z:
        h = float(core[0, 0])
        wx0 = ox + x0 * vs
        wy0 = oy + y0 * vs
        wx1 = ox + x1 * vs
        wy1 = oy + y1 * vs
        _add(
            np.array((((wx0, wy0, h), (wx1, wy0, h), (wx1, wy1, h), (wx0, wy1, h)),), dtype=np.float32),
            _axis_normals(1, 2, 1.0),
        )
        _add_skirts(merge=True)
        if h > bottom + _MERGE_Z:
            _add(
                np.array(
                    (((wx0, wy0, bottom), (wx0, wy1, bottom), (wx1, wy1, bottom), (wx1, wy0, bottom)),),
                    dtype=np.float32,
                ),
                _axis_normals(1, 2, -1.0),
            )
        if not parts_c:
            return []
        return pack_quad_meshes(np.concatenate(parts_c, axis=0), np.concatenate(parts_n, axis=0), DEFAULT_COLOR)

    merge = _neighbor_merge_frac(valid, core) >= _GREEDY_MIN_MERGE_FRAC
    if merge:
        tops = _greedy_flat_quads(valid, core, ox, oy, x0, y0, vs)
    else:
        tops = _top_quads(valid, core, ox, oy, x0, y0, vs)
    _add(tops, _axis_normals(tops.shape[0], 2, 1.0))
    _add_skirts(merge=merge)
    thick = valid & (core > bottom + _MERGE_Z)
    if thick.all():
        wx0 = ox + x0 * vs
        wy0 = oy + y0 * vs
        wx1 = ox + x1 * vs
        wy1 = oy + y1 * vs
        bots = np.array(
            (((wx0, wy0, bottom), (wx0, wy1, bottom), (wx1, wy1, bottom), (wx1, wy0, bottom)),),
            dtype=np.float32,
        )
    else:
        bots = _greedy_flat_quads(thick, None, ox, oy, x0, y0, vs, z_const=bottom, reverse_winding=True)
    _add(bots, _axis_normals(bots.shape[0], 2, -1.0))
    if not parts_c:
        return []
    return pack_quad_meshes(np.concatenate(parts_c, axis=0), np.concatenate(parts_n, axis=0), DEFAULT_COLOR)
