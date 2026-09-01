"""2D laser-engrave occupancy used as a world-space stock decal."""

from __future__ import annotations

import math

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
    compress_array,
    compressed_nbytes,
    decompress_array,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds

LASER_MODE_PLANAR = "planar"
LASER_MODE_CYLINDRICAL = "cylindrical"

# Decal is independent of occupancy: finer cells, ~0.1 mm beam, GPU-size cap.
LASER_RES_MULT = 4
LASER_CELL_MIN_MM = 0.025
LASER_CELL_MAX_MM = 0.05
LASER_MAX_DIM = 4096
LASER_BEAM_RADIUS_MIN_MM = 0.08
LASER_BEAM_RADIUS_MAX_MM = 0.12

# Firmware laser PWM is S in 0–1. Gamma-lift so low duty still reads on beige.
LASER_PREVIEW_GAMMA = 0.3


def laser_burn_uint8(power_s: float | None) -> np.uint8:
    """Map laser S (0–1 PWM) to a preview luminance texel.

    Missing S is full power. S above 1 is full unless it looks like mill RPM.
    """
    if power_s is None:
        return np.uint8(255)
    s = float(power_s)
    if s <= 0.0:
        return np.uint8(0)
    if s > 1.0:
        if s > 100.0 + 1e-9:
            return np.uint8(0)
        s = 1.0
    visual = s**LASER_PREVIEW_GAMMA
    return np.uint8(min(255, int(round(visual * 255.0))))


def pick_laser_cell_size_mm(
    bounds: StockBounds,
    occupancy_cell_mm: float,
    *,
    cylindrical: bool = False,
    max_dim: int = LASER_MAX_DIM,
) -> float:
    """Cell size for the world-space decal; at least 4× occupancy, capped for GPU memory."""
    occ = max(float(occupancy_cell_mm), 1e-9)
    cell = min(occ / float(LASER_RES_MULT), LASER_CELL_MAX_MM)
    cell = max(cell, LASER_CELL_MIN_MM)
    sx, sy, sz = bounds.size
    if cylindrical:
        span = max(float(sx), math.pi * min(float(sy), float(sz)), 1e-6)
    else:
        span = max(float(sx), float(sy), 1e-6)
    cap = max(int(max_dim), 8)
    if span / cell > cap:
        cell = span / cap
    return float(cell)


def stroke_radius_mm(cell_size: float) -> float:
    """Beam width in mm. Tied to the decal cell, not occupancy, so rasters do not blob."""
    return max(LASER_BEAM_RADIUS_MIN_MM, min(LASER_BEAM_RADIUS_MAX_MM, 0.9 * float(cell_size)))


LASER_SNAP_FULL = "full"
LASER_SNAP_DELTA = "delta"
LASER_SNAP_DROP = "drop"

# COO row is (iu, iv, value); 2×uint32 + uint8, padded in a uint32 triple.
_DELTA_BYTES_PER_TEXEL = 9


def compress_laser_sparse(rs: np.ndarray, cs: np.ndarray, vals: np.ndarray, shape: tuple[int, ...]) -> object:
    """Pack changed texels as a zlib’d ``(N, 3)`` uint32 table plus the map shape."""
    pack = np.empty((int(rs.size), 3), dtype=np.uint32)
    pack[:, 0] = rs
    pack[:, 1] = cs
    pack[:, 2] = np.asarray(vals, dtype=np.uint8)
    return (tuple(int(s) for s in shape), compress_array(pack))


def decompress_laser_sparse(blob: object) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, ...]]:
    """Inverse of :func:`compress_laser_sparse`."""
    shape, packed = blob  # type: ignore[misc]
    pack = decompress_array(packed)
    return pack[:, 0], pack[:, 1], pack[:, 2].astype(np.uint8, copy=False), tuple(int(s) for s in shape)


def laser_diff_payload(prev: np.ndarray | None, curr: np.ndarray) -> object | None:
    """Tagged snapshot of ``curr`` vs ``prev``. ``None`` if unchanged.

    Falls back to a full map when a sparse COO would be larger than half the bitmap.
    Missing or mismatched ``prev`` is a full snapshot (first paint / new shape).
    """
    curr = np.ascontiguousarray(curr)
    if prev is None or prev.shape != curr.shape:
        return (LASER_SNAP_FULL, compress_array(curr))
    changed = prev != curr
    n = int(np.count_nonzero(changed))
    if n == 0:
        return None
    if n * _DELTA_BYTES_PER_TEXEL > curr.nbytes / 2:
        return (LASER_SNAP_FULL, compress_array(curr))
    rs, cs = np.nonzero(changed)
    return (LASER_SNAP_DELTA, compress_laser_sparse(rs, cs, curr[rs, cs], curr.shape))


def apply_laser_tagged(laser: LaserMap, payload: object) -> None:
    """Apply a tagged laser extra onto ``laser`` (caller ensures the map exists)."""
    if not isinstance(payload, tuple) or not payload:
        laser.restore(payload)
        return
    kind = payload[0]
    if kind == LASER_SNAP_FULL and len(payload) >= 2:
        laser.restore(payload[1])
        return
    if kind == LASER_SNAP_DELTA and len(payload) >= 2:
        rs, cs, vals, shape = decompress_laser_sparse(payload[1])
        if laser.intensity.shape != shape:
            laser.intensity[:, :] = 0
            return
        laser.intensity[rs, cs] = vals
        return
    laser.restore(payload)


def laser_snapshot_nbytes(blob: object) -> int:
    """Byte estimate for a tagged laser extra (full / delta / drop)."""
    if blob is None:
        return 0
    if not isinstance(blob, tuple) or not blob:
        return compressed_nbytes(blob)
    kind = blob[0]
    if kind == LASER_SNAP_DROP:
        return 8
    if kind in (LASER_SNAP_FULL, LASER_SNAP_DELTA) and len(blob) >= 2:
        data = blob[1]
        if kind == LASER_SNAP_DELTA and isinstance(data, tuple) and len(data) >= 2:
            return compressed_nbytes(data[1])
        return compressed_nbytes(data)
    return compressed_nbytes(blob)


def attach_laser_snapshot(payload: tuple, laser: LaserMap | None) -> tuple:
    """Keep occupancy 2-tuples unchanged until a map exists."""
    if laser is None:
        return payload
    return payload + ((LASER_SNAP_FULL, laser.snapshot()),)


def split_laser_snapshot(payload: object) -> tuple[object, object | None]:
    """Return ``(occupancy_payload, laser_payload_or_none)``."""
    if isinstance(payload, tuple) and len(payload) >= 3 and payload[0] in ("full", "delta"):
        return payload[:2], payload[2]
    return payload, None


class LaserMap:
    """uint8 intensity over planar XY or cylindrical (x, θ).

    Allocated lazily by backends on the first successful paint.
    """

    def __init__(
        self,
        *,
        nx: int,
        nv: int,
        cell_u: float,
        origin_u: float,
        mode: str,
        cell_v: float | None = None,
        origin_v: float = 0.0,
        wrap_v: bool = False,
        v_period: float | None = None,
        v_scale: float = 1.0,
    ):
        self.nx = max(1, int(nx))
        self.nv = max(1, int(nv))
        self.cell_u = float(cell_u)
        self.cell_v = float(cell_v if cell_v is not None else cell_u)
        self.origin_u = float(origin_u)
        self.origin_v = float(origin_v)
        self.mode = str(mode)
        self.wrap_v = bool(wrap_v)
        self.v_period = float(v_period) if v_period is not None else (360.0 if wrap_v else 0.0)
        self.v_scale = float(v_scale) if v_scale else 1.0
        self.intensity = np.zeros((self.nx, self.nv), dtype=np.uint8)

    @classmethod
    def planar(cls, bounds: StockBounds, nx: int, ny: int, cell_size: float) -> LaserMap:
        return cls(
            nx=nx,
            nv=ny,
            cell_u=cell_size,
            origin_u=bounds.min_x,
            mode=LASER_MODE_PLANAR,
            cell_v=cell_size,
            origin_v=bounds.min_y,
            wrap_v=False,
        )

    @classmethod
    def cylindrical(
        cls,
        bounds: StockBounds,
        nx: int,
        n_theta: int,
        cell_size: float,
        d_theta: float,
    ) -> LaserMap:
        """``v`` is stock θ (deg), matching mill occupancy and the carved-stock shader."""
        return cls(
            nx=nx,
            nv=n_theta,
            cell_u=cell_size,
            origin_u=bounds.min_x,
            mode=LASER_MODE_CYLINDRICAL,
            cell_v=d_theta,
            origin_v=0.0,
            wrap_v=True,
            v_period=360.0,
            v_scale=float(cell_size) / max(float(d_theta), 1e-12),
        )

    def intensity_at(self, u: float, v: float) -> int:
        iu, iv = self._index(u, v)
        if iu is None:
            return 0
        return int(self.intensity[iu, iv])

    def paint_segment(
        self,
        u0: float,
        v0: float,
        u1: float,
        v1: float,
        radius: float,
        allow: np.ndarray | None = None,
        *,
        allow_origin: tuple[int, int] | None = None,
        burn: np.uint8 | int,
    ) -> bool:
        """Burn a 2D capsule. ``allow`` is True where stock still exists (window-aligned)."""
        value = np.uint8(int(burn))
        if not value:
            return False
        return self._stamp(u0, v0, u1, v1, radius, value, allow, allow_origin)

    def clear_segment(self, u0: float, v0: float, u1: float, v1: float, radius: float) -> bool:
        """Zero a 2D capsule (mill-over-engrave on a decoupled grid)."""
        return self._stamp(u0, v0, u1, v1, radius, np.uint8(0), None, None)

    def clear_window(self, iu0: int, iv0: int, mask: np.ndarray) -> bool:
        """Zero a contiguous window where ``mask`` is True (same grid as occupancy)."""
        if mask.size == 0 or not mask.any():
            return False
        rows, cols = mask.shape
        iu0 = int(iu0)
        iv0 = int(iv0)
        slab = self.intensity[iu0 : iu0 + rows, iv0 : iv0 + cols]
        if slab.shape != mask.shape:
            return False
        if not np.any(slab[mask]):
            return False
        slab[mask] = 0
        return True

    def clear_indexed(self, iu0: int, iv_indices: np.ndarray, mask: np.ndarray) -> bool:
        """Zero ``intensity[iu0+i, iv_indices[j]]`` where ``mask[i, j]`` (θ subsets / wrap)."""
        if mask.size == 0 or not mask.any():
            return False
        rs, cs = np.nonzero(mask)
        if rs.size == 0:
            return False
        iu = int(iu0) + rs
        iv = np.asarray(iv_indices, dtype=np.int32)[cs]
        if self.wrap_v:
            iv %= self.nv
        valid = (iu >= 0) & (iu < self.nx) & (iv >= 0) & (iv < self.nv)
        if not valid.any():
            return False
        iu = iu[valid]
        iv = iv[valid]
        if not np.any(self.intensity[iu, iv]):
            return False
        self.intensity[iu, iv] = 0
        return True

    def clear_from_coarse_mask(
        self,
        mask: np.ndarray,
        coarse_iu0: int,
        coarse_iv0: int | np.ndarray,
        coarse_cell_u: float,
        coarse_cell_v: float,
        coarse_origin_u: float,
        coarse_origin_v: float,
        *,
        coarse_nv: int | None = None,
    ) -> bool:
        """Zero laser texels whose centers fall in True occupancy cells (any resolution)."""
        if mask.size == 0 or not np.any(mask):
            return False
        rows, cols = mask.shape
        cu = max(float(coarse_cell_u), 1e-12)
        cv = max(float(coarse_cell_v), 1e-12)
        iu0 = int(coarse_iu0)

        if isinstance(coarse_iv0, np.ndarray):
            ncv = int(
                coarse_nv if coarse_nv is not None else (int(np.max(coarse_iv0)) + 1 if coarse_iv0.size else cols)
            )
            ncv = max(ncv, 1)
            iv = np.asarray(coarse_iv0, dtype=np.int32)
            if iv.size != cols:
                return False
            if self.wrap_v:
                iv %= ncv
            full = np.zeros((rows, ncv), dtype=bool)
            full[:, iv] = mask
            mask = full
            cols = ncv
            coarse_iv0_i = 0
            coarse_nv = ncv
        else:
            coarse_iv0_i = int(coarse_iv0)

        u0 = float(coarse_origin_u) + iu0 * cu
        u1 = u0 + rows * cu
        lu0 = max(0, int(math.floor((u0 - self.origin_u) / max(self.cell_u, 1e-12))))
        lu1 = min(self.nx - 1, int(math.floor((u1 - 1e-9 - self.origin_u) / max(self.cell_u, 1e-12))))
        if lu0 > lu1:
            return False
        uu = self.origin_u + (np.arange(lu0, lu1 + 1, dtype=np.float64) + 0.5) * self.cell_u
        ci = np.floor((uu - float(coarse_origin_u)) / cu).astype(np.int32) - iu0
        ok_i = (ci >= 0) & (ci < rows)

        if self.wrap_v:
            period = self.v_period if self.v_period else 360.0
            ncv = int(coarse_nv if coarse_nv is not None else cols)
            vv = self.origin_v + (np.arange(self.nv, dtype=np.float64) + 0.5) * self.cell_v
            vv = np.mod(vv - float(coarse_origin_v), period) + float(coarse_origin_v)
            cj = np.floor((vv - float(coarse_origin_v)) / cv).astype(np.int32)
            if ncv > 0:
                cj %= ncv
            cj = cj - coarse_iv0_i
            ok_j = (cj >= 0) & (cj < cols)
            shape = (lu1 - lu0 + 1, self.nv)
            valid = ok_i[:, None] & ok_j[None, :]
            if not valid.any():
                return False
            sampled = np.zeros(shape, dtype=bool)
            ci_b = np.broadcast_to(ci[:, None], shape)
            cj_b = np.broadcast_to(cj[None, :], shape)
            sampled[valid] = mask[ci_b[valid], cj_b[valid]]
            if not sampled.any():
                return False
            slab = self.intensity[lu0 : lu1 + 1, :]
            if not np.any(slab[sampled]):
                return False
            slab[sampled] = 0
            return True

        iv0 = coarse_iv0_i
        v0 = float(coarse_origin_v) + iv0 * cv
        v1 = v0 + cols * cv
        lv0 = max(0, int(math.floor((v0 - self.origin_v) / max(self.cell_v, 1e-12))))
        lv1 = min(self.nv - 1, int(math.floor((v1 - 1e-9 - self.origin_v) / max(self.cell_v, 1e-12))))
        if lv0 > lv1:
            return False
        vv = self.origin_v + (np.arange(lv0, lv1 + 1, dtype=np.float64) + 0.5) * self.cell_v
        cj = np.floor((vv - float(coarse_origin_v)) / cv).astype(np.int32) - iv0
        ok_j = (cj >= 0) & (cj < cols)
        shape = (lu1 - lu0 + 1, lv1 - lv0 + 1)
        valid = ok_i[:, None] & ok_j[None, :]
        if not valid.any():
            return False
        sampled = np.zeros(shape, dtype=bool)
        ci_b = np.broadcast_to(ci[:, None], shape)
        cj_b = np.broadcast_to(cj[None, :], shape)
        sampled[valid] = mask[ci_b[valid], cj_b[valid]]
        if not sampled.any():
            return False
        slab = self.intensity[lu0 : lu1 + 1, lv0 : lv1 + 1]
        if not np.any(slab[sampled]):
            return False
        slab[sampled] = 0
        return True

    def gpu_payload(self) -> tuple[int, int, bytes, str]:
        """``(width, height, luminance_bytes, mode)`` with v as texture T (row)."""
        pixels = np.ascontiguousarray(self.intensity.T)
        return (self.nx, self.nv, pixels.tobytes(), self.mode)

    def snapshot(self) -> object:
        return compress_array(self.intensity)

    def restore(self, payload: object) -> None:
        restored = decompress_array(payload)
        if restored.shape != self.intensity.shape:
            self.intensity[:, :] = 0
            return
        self.intensity[:, :] = restored

    def _index(self, u: float, v: float) -> tuple[int | None, int | None]:
        iu = int(math.floor((float(u) - self.origin_u) / max(self.cell_u, 1e-12)))
        if self.wrap_v:
            period = self.v_period if self.v_period else 360.0
            vv = float(v) % period
            if vv < 0:
                vv += period
            iv = int(math.floor((vv - self.origin_v) / max(self.cell_v, 1e-12))) % self.nv
        else:
            iv = int(math.floor((float(v) - self.origin_v) / max(self.cell_v, 1e-12)))
        if not (0 <= iu < self.nx and 0 <= iv < self.nv):
            return None, None
        return iu, iv

    def _stamp(
        self,
        u0: float,
        v0: float,
        u1: float,
        v1: float,
        radius: float,
        value: np.uint8,
        allow: np.ndarray | None,
        allow_origin: tuple[int, int] | None,
    ) -> bool:
        radius = max(float(radius), 0.71 * float(self.cell_u), 0.0)
        pad_u = radius + self.cell_u
        pad_v = radius / max(self.v_scale, 1e-12) + self.cell_v
        iu0 = int(math.floor((min(u0, u1) - pad_u - self.origin_u) / max(self.cell_u, 1e-12)))
        iu1 = int(math.floor((max(u0, u1) + pad_u - self.origin_u) / max(self.cell_u, 1e-12)))
        iu0 = max(0, iu0)
        iu1 = min(self.nx - 1, iu1)
        if iu0 > iu1:
            return False

        if self.wrap_v:
            iv_idx = self._wrapped_v_indices(v0, v1, pad_v)
            if iv_idx.size == 0:
                return False
            uu = self.origin_u + (np.arange(iu0, iu1 + 1, dtype=np.float64) + 0.5) * self.cell_u
            vv = self.origin_v + (iv_idx.astype(np.float64) + 0.5) * self.cell_v
            v0u, v1u = _unwrap_v_segment(v0, v1, self.v_period)
            hit = _capsule_hit_wrapped(
                uu[:, None],
                vv[None, :],
                u0,
                v0u,
                u1,
                v1u,
                radius,
                self.v_period,
                self.v_scale,
            )
            if allow is not None:
                hit = hit & _allow_for_indexed(allow, allow_origin, iu0, iv_idx, hit.shape)
            if not hit.any():
                return False
            rs, cs = np.nonzero(hit)
            iu = iu0 + rs
            iv = iv_idx[cs] % self.nv
            if value:
                before = self.intensity[iu, iv]
                painted = np.maximum(before, value)
                if np.all(painted == before):
                    return False
                self.intensity[iu, iv] = painted
            else:
                if not np.any(self.intensity[iu, iv]):
                    return False
                self.intensity[iu, iv] = 0
            return True

        iv0 = int(math.floor((min(v0, v1) - pad_v - self.origin_v) / max(self.cell_v, 1e-12)))
        iv1 = int(math.floor((max(v0, v1) + pad_v - self.origin_v) / max(self.cell_v, 1e-12)))
        iv0 = max(0, iv0)
        iv1 = min(self.nv - 1, iv1)
        if iv0 > iv1:
            return False
        uu = self.origin_u + (np.arange(iu0, iu1 + 1, dtype=np.float64) + 0.5) * self.cell_u
        vv = self.origin_v + (np.arange(iv0, iv1 + 1, dtype=np.float64) + 0.5) * self.cell_v
        hit = _capsule_hit(uu[:, None], vv[None, :], u0, v0, u1, v1, radius, self.v_scale)
        if allow is not None:
            hit = hit & _allow_for_window(allow, allow_origin, iu0, iv0, hit.shape)
        if not hit.any():
            return False
        slab = self.intensity[iu0 : iu1 + 1, iv0 : iv1 + 1]
        if value:
            prev = slab[hit]
            if np.all(prev >= value):
                return False
            slab[hit] = np.maximum(prev, value)
        else:
            if not np.any(slab[hit]):
                return False
            slab[hit] = 0
        return True

    def _wrapped_v_indices(self, v0: float, v1: float, pad_v: float) -> np.ndarray:
        period = self.v_period if self.v_period else 360.0
        v0u, v1u = _unwrap_v_segment(v0, v1, period)
        span = abs(v1u - v0u) + 2.0 * pad_v
        if span >= period - 1e-6:
            return np.arange(self.nv, dtype=np.int32)
        lo = min(v0u, v1u) - pad_v
        n = int(math.ceil(span / max(self.cell_v, 1e-12))) + 2
        i0 = int(math.floor((lo - self.origin_v) / max(self.cell_v, 1e-12)))
        return (i0 + np.arange(n + 1, dtype=np.int32)) % self.nv


def _unwrap_v_segment(v0: float, v1: float, period: float) -> tuple[float, float]:
    """Return ``(v0, v1)`` unwrapped along the short arc, unless travel is a full turn."""
    period = float(period) if period else 360.0
    v0 = float(v0)
    v1 = float(v1)
    dv = v1 - v0
    if abs(dv) >= period - 1e-6:
        return v0, v0 + period
    dv = (dv + period * 0.5) % period - period * 0.5
    return v0, v0 + dv


def _capsule_hit(
    uu: np.ndarray,
    vv: np.ndarray,
    u0: float,
    v0: float,
    u1: float,
    v1: float,
    radius: float,
    v_scale: float = 1.0,
) -> np.ndarray:
    scale = float(v_scale) if v_scale else 1.0
    du = float(u1) - float(u0)
    dv = (float(v1) - float(v0)) * scale
    len_sq = du * du + dv * dv
    r_cov = float(radius) + 1e-9
    vv_mm = vv * scale
    v0_mm = float(v0) * scale
    if len_sq < 1e-18:
        dist_sq = (uu - u0) ** 2 + (vv_mm - v0_mm) ** 2
        return dist_sq <= r_cov * r_cov
    t = ((uu - u0) * du + (vv_mm - v0_mm) * dv) / len_sq
    t = np.clip(t, 0.0, 1.0)
    dist_sq = (uu - (u0 + t * du)) ** 2 + (vv_mm - (v0_mm + t * dv)) ** 2
    return dist_sq <= r_cov * r_cov


def _capsule_hit_wrapped(
    uu: np.ndarray,
    vv: np.ndarray,
    u0: float,
    v0: float,
    u1: float,
    v1: float,
    radius: float,
    period: float,
    v_scale: float = 1.0,
) -> np.ndarray:
    """Min distance to the capsule over ``vv``, ``vv±period`` (θ wrap)."""
    period = float(period) if period else 360.0
    hit = _capsule_hit(uu, vv, u0, v0, u1, v1, radius, v_scale)
    hit |= _capsule_hit(uu, vv + period, u0, v0, u1, v1, radius, v_scale)
    hit |= _capsule_hit(uu, vv - period, u0, v0, u1, v1, radius, v_scale)
    return hit


def _allow_for_window(
    allow: np.ndarray,
    origin: tuple[int, int] | None,
    iu0: int,
    iv0: int,
    shape: tuple[int, int],
) -> np.ndarray:
    if origin is None:
        if allow.shape == shape:
            return allow.astype(bool, copy=False)
        return np.ones(shape, dtype=bool)
    au0, av0 = origin
    out = np.zeros(shape, dtype=bool)
    # Overlap of stamp window (iu0, iv0) with allow origin.
    rows, cols = allow.shape
    rs0 = max(0, au0 - iu0)
    cs0 = max(0, av0 - iv0)
    rs1 = min(shape[0], au0 + rows - iu0)
    cs1 = min(shape[1], av0 + cols - iv0)
    if rs0 >= rs1 or cs0 >= cs1:
        return out
    as0 = rs0 + iu0 - au0
    ac0 = cs0 + iv0 - av0
    out[rs0:rs1, cs0:cs1] = allow[as0 : as0 + (rs1 - rs0), ac0 : ac0 + (cs1 - cs0)]
    return out


def _allow_for_indexed(
    allow: np.ndarray,
    origin: tuple[int, int] | None,
    iu0: int,
    iv_idx: np.ndarray,
    shape: tuple[int, int],
) -> np.ndarray:
    rows, cols = shape
    au0, av0 = (0, 0) if origin is None else origin
    iu = np.broadcast_to(
        (int(iu0) - au0) + np.arange(rows, dtype=np.int32)[:, None],
        shape,
    )
    iv = np.broadcast_to(np.asarray(iv_idx, dtype=np.int32)[None, :] - av0, shape)
    ok = (iu >= 0) & (iu < allow.shape[0]) & (iv >= 0) & (iv < allow.shape[1])
    out = np.zeros(shape, dtype=bool)
    if ok.any():
        out[ok] = allow[iu[ok], iv[ok]]
    return out


class LaserDecalMixin:
    """Lazy laser map owned by a carver backend. Mill-clear is a no-op until first paint."""

    _laser: LaserMap | None
    _laser_dirty: bool
    _laser_cp_baseline: np.ndarray | None

    def _init_laser(self) -> None:
        self._laser = None
        self._laser_dirty = False
        self._laser_cp_baseline = None

    def _drop_laser(self) -> None:
        # Keep ``_laser_cp_baseline`` so the next delta CP can emit ``("drop",)``.
        # Mark dirty when a map existed so occupancy reset still drops the GPU texture.
        had = self._laser is not None
        self._laser = None
        if had:
            self._laser_dirty = True

    def _ensure_laser(self) -> LaserMap:
        if self._laser is None:
            self._laser = self._make_laser_map()
        return self._laser

    def _make_laser_map(self) -> LaserMap:
        raise NotImplementedError

    def _commit_laser_baseline(self) -> None:
        if self._laser is None:
            self._laser_cp_baseline = None
        else:
            self._laser_cp_baseline = self._laser.intensity.copy()

    def laser_checkpoint_full(self) -> object | None:
        """Tagged full extra for a GOP base slot, or ``None`` if no map."""
        if self._laser is None:
            self._laser_cp_baseline = None
            return None
        snap = (LASER_SNAP_FULL, self._laser.snapshot())
        self._commit_laser_baseline()
        return snap

    def laser_checkpoint_delta(self) -> object | None:
        """Tagged extra vs the last recorded CP, or ``None`` if unchanged / still empty."""
        if self._laser is None:
            if self._laser_cp_baseline is None:
                return None
            self._laser_cp_baseline = None
            return (LASER_SNAP_DROP,)
        snap = laser_diff_payload(self._laser_cp_baseline, self._laser.intensity)
        self._commit_laser_baseline()
        return snap

    def take_laser_dirty(self) -> bool:
        dirty = bool(self._laser_dirty)
        self._laser_dirty = False
        return dirty

    def laser_gpu_payload(self) -> tuple[int, int, bytes, str] | None:
        if self._laser is None:
            return None
        return self._laser.gpu_payload()

    def _restore_laser_payload(self, laser_payload: object | None, *, occupancy_kind: str = "full") -> None:
        """Apply a tagged laser extra. Omitted extra drops on occupancy-full, else leaves as-is."""
        if laser_payload is None:
            if occupancy_kind == "full":
                self._drop_laser()
                self._laser_cp_baseline = None
                return
            self._commit_laser_baseline()
            return
        if isinstance(laser_payload, tuple) and laser_payload and laser_payload[0] == LASER_SNAP_DROP:
            self._drop_laser()
            self._laser_cp_baseline = None
            return
        kind = laser_payload[0] if isinstance(laser_payload, tuple) and laser_payload else None
        if kind == LASER_SNAP_DELTA:
            if self._laser is None:
                self._laser = self._make_laser_map()
            apply_laser_tagged(self._laser, laser_payload)
            self._laser_dirty = True
            self._commit_laser_baseline()
            return
        laser = self._ensure_laser()
        apply_laser_tagged(laser, laser_payload)
        self._laser_dirty = True
        self._commit_laser_baseline()

    def _snapshot_with_laser(self, payload: tuple, *, full: bool) -> tuple:
        extra = self.laser_checkpoint_full() if full else self.laser_checkpoint_delta()
        if extra is None:
            return payload
        return payload + (extra,)
