"""Tiled Z-heightmap stock carver (fast 3-axis / non-undercutting tools)."""

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
    tile_keys_from_window_mask,
)
from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, TileKey
from carveracontroller.addons.stock.simulator.carvers.heightmap.mesh import (
    _OUTSIDE,
)
from carveracontroller.addons.stock.simulator.carvers.heightmap.mesh import (
    mesh_heightmap_region as _mesh_heightmap_region,
)
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LaserDecalMixin,
    LaserMap,
    laser_burn_uint8,
    pick_laser_cell_size_mm,
    split_laser_snapshot,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import (
    CylindricalStock,
    RectangularStock,
    RotaryCylindricalStock,
    StockShape,
)


def pick_heightmap_size(bounds: StockBounds, cell_size_mm: float) -> tuple[int, int]:
    sx, sy, _sz = bounds.size
    nx = max(1, int(math.ceil(sx / max(cell_size_mm, 1e-9))))
    ny = max(1, int(math.ceil(sy / max(cell_size_mm, 1e-9))))
    return nx, ny


def _sample_profile_z_for_radius(
    profile_zs: np.ndarray,
    profile_rs: np.ndarray,
    dist_xy: np.ndarray,
) -> np.ndarray:
    """Smallest tool-relative Z where profile radius >= dist_xy (inverse profile)."""
    out = np.full(dist_xy.shape, np.inf, dtype=np.float64)
    if profile_zs.size == 0:
        return out
    max_r = float(np.max(profile_rs))
    min_r = float(np.min(profile_rs))
    if max_r - min_r < 1e-12:
        np.copyto(out, float(profile_zs[0]), where=dist_xy <= max_r + 1e-9)
        return out

    flat = dist_xy.ravel()
    result = np.full(flat.shape, np.inf, dtype=np.float64)
    inside = flat <= max_r + 1e-9
    if not inside.any():
        return out

    # Non-undercut tools (the heightmap's intended case): invert with searchsorted.
    if bool(np.all(np.diff(profile_rs) >= -1e-12)):
        d = flat[inside]
        idx = np.searchsorted(profile_rs, d, side="left")
        idx = np.minimum(idx, profile_rs.size - 1)
        z = np.empty_like(d)
        first = idx == 0
        z[first] = float(profile_zs[0])
        later = ~first
        if later.any():
            i1 = idx[later]
            i0 = i1 - 1
            r0 = profile_rs[i0]
            r1 = profile_rs[i1]
            z0 = profile_zs[i0]
            z1 = profile_zs[i1]
            denom = r1 - r0
            t = np.zeros_like(d[later])
            steep = np.abs(denom) >= 1e-12
            if steep.any():
                t[steep] = np.clip((d[later][steep] - r0[steep]) / denom[steep], 0.0, 1.0)
            z[later] = np.where(steep, z0 + t * (z1 - z0), np.minimum(z0, z1))
        result[inside] = z
        return result.reshape(dist_xy.shape)

    # Re-entrant silhouette: smallest Z on any segment where r(z) >= dist.
    d = flat[inside]
    z_best = np.full(d.shape, np.inf, dtype=np.float64)
    for i in range(len(profile_zs) - 1):
        z0, z1 = float(profile_zs[i]), float(profile_zs[i + 1])
        r0, r1 = float(profile_rs[i]), float(profile_rs[i + 1])
        cand = np.full(d.shape, np.inf, dtype=np.float64)
        at_start = d <= r0 + 1e-9
        cand[at_start] = z0
        if abs(r1 - r0) >= 1e-12:
            crosses = (~at_start) & (d <= r1 + 1e-9)
            if crosses.any():
                t = np.clip((d[crosses] - r0) / (r1 - r0), 0.0, 1.0)
                cand[crosses] = z0 + t * (z1 - z0)
        z_best = np.minimum(z_best, cand)
    for z, r in zip(profile_zs, profile_rs):
        z_best = np.minimum(z_best, np.where(d <= float(r) + 1e-9, float(z), np.inf))
    result[inside] = z_best
    return result.reshape(dist_xy.shape)


def _cut_z_along_segment(
    t: np.ndarray,
    p0: tuple[float, float, float],
    dx: float,
    dy: float,
    dz: float,
    wx: np.ndarray,
    wy: np.ndarray,
    profile_zs: np.ndarray,
    profile_rs: np.ndarray,
    *,
    clamp_r: float | None = None,
) -> np.ndarray:
    """Remaining world Z at poses ``p0 + t * Δ`` for each XY sample.

    ``clamp_r`` caps XY distance before the profile lookup. Coverage-interval
    endpoints are constructed to lie on the max-radius circle; reconstructing
    that distance with ``hypot`` can land 1 ULP outside and drop the sample.
    """
    dist = np.hypot(wx - (p0[0] + t * dx), wy - (p0[1] + t * dy))
    if clamp_r is not None:
        dist = np.minimum(dist, float(clamp_r))
    z_rel = _sample_profile_z_for_radius(profile_zs, profile_rs, dist)
    return (p0[2] + t * dz) + z_rel


class HeightmapBackend(LaserDecalMixin):
    """Single remaining top-Z per XY cell."""

    kind = "heightmap"

    def __init__(
        self,
        bounds: StockBounds,
        cell_size_mm: float,
        shape: StockShape | None = None,
        tile_size: int = DEFAULT_TILE_SIZE,
        *,
        heights: np.ndarray | None = None,
        seed: bool = True,
        index_origin: tuple[int, int] = (0, 0),
        laser_cell_size_mm: float | None = None,
    ):
        self.bounds = bounds
        self.cell_size = float(cell_size_mm)
        self._laser_cell_size = (
            float(laser_cell_size_mm)
            if laser_cell_size_mm is not None
            else pick_laser_cell_size_mm(bounds, self.cell_size)
        )
        self.tile_size = max(2, int(tile_size))
        self.shape: StockShape = shape or RectangularStock(
            width_mm=max(bounds.size[0], 1e-6),
            length_mm=max(bounds.size[1], 1e-6),
            height_mm=max(bounds.size[2], 1e-6),
        )
        self.nx, self.ny = pick_heightmap_size(bounds, self.cell_size)
        self.n_tiles_x = max(1, int(math.ceil(self.nx / self.tile_size)))
        self.n_tiles_y = max(1, int(math.ceil(self.ny / self.tile_size)))
        self._ox, self._oy = int(index_origin[0]), int(index_origin[1])
        self._touched: set[TileKey] = set()
        if heights is not None:
            self.heights = heights
        else:
            self._ox = self._oy = 0
            self.heights = np.full((self.nx, self.ny), _OUTSIDE, dtype=np.float32)
            if seed:
                self._seed_heights()
        self._init_laser()

    def _world_xy(self, ix: np.ndarray, iy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        wx = self.bounds.min_x + (ix.astype(np.float64) + 0.5) * self.cell_size
        wy = self.bounds.min_y + (iy.astype(np.float64) + 0.5) * self.cell_size
        return wx, wy

    def _fill_seed(self, out: np.ndarray) -> None:
        ix = np.arange(self.nx)
        iy = np.arange(self.ny)
        XX, YY = np.meshgrid(ix, iy, indexing="ij")
        wx, wy = self._world_xy(XX, YY)
        top = float(self.bounds.max_z)
        bottom = float(self.bounds.min_z)
        shape = self.shape

        if isinstance(shape, RectangularStock):
            out[:, :] = np.float32(top)
            return

        if isinstance(shape, CylindricalStock):
            cx = 0.5 * (self.bounds.min_x + self.bounds.max_x)
            cy = 0.5 * (self.bounds.min_y + self.bounds.max_y)
            r = 0.5 * float(shape.diameter_mm)
            inside = (wx - cx) ** 2 + (wy - cy) ** 2 <= r * r + 1e-9
            out[:, :] = _OUTSIDE
            out[inside] = np.float32(top)
            return

        if isinstance(shape, RotaryCylindricalStock):
            cy = 0.5 * (self.bounds.min_y + self.bounds.max_y)
            cz = 0.5 * (self.bounds.min_z + self.bounds.max_z)
            r = 0.5 * float(shape.diameter_mm)
            dy = wy - cy
            inside = np.abs(dy) <= r + 1e-9
            z_top = cz + np.sqrt(np.maximum(r * r - dy * dy, 0.0))
            out[:, :] = _OUTSIDE
            out[inside] = np.float32(z_top[inside])
            np.clip(out, bottom, top, out=out, where=inside)
            return

        out[:, :] = np.float32(top)

    def _seed_heights(self) -> None:
        self._fill_seed(self.heights)

    def reset_occupancy(self) -> set[TileKey]:
        self.heights[:, :] = _OUTSIDE
        self._ox = self._oy = 0
        self._seed_heights()
        self._touched.clear()
        self._drop_laser()
        return self.initial_surface_keys()

    def clone_empty(self) -> HeightmapBackend:
        return HeightmapBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.tile_size,
            seed=True,
            laser_cell_size_mm=self._laser_cell_size,
        )

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
        del a0, a1
        profile = resolve_cutting_profile(tool_def, tool_unit_scale=tool_unit_scale)
        if not profile:
            return set()
        max_r = max(r for _z, r in profile)
        if max_r <= 0:
            return set()
        profile_zs = np.array([z for z, _r in profile], dtype=np.float64)
        profile_rs = np.array([r for _z, r in profile], dtype=np.float64)

        pad = max_r + self.cell_size
        min_x = min(p0[0], p1[0]) - pad
        max_x = max(p0[0], p1[0]) + pad
        min_y = min(p0[1], p1[1]) - pad
        max_y = max(p0[1], p1[1]) + pad

        ix0 = max(0, int(math.floor((min_x - self.bounds.min_x) / self.cell_size)))
        iy0 = max(0, int(math.floor((min_y - self.bounds.min_y) / self.cell_size)))
        ix1 = min(self.nx - 1, int(math.floor((max_x - self.bounds.min_x) / self.cell_size)))
        iy1 = min(self.ny - 1, int(math.floor((max_y - self.bounds.min_y) / self.cell_size)))
        if ix0 > ix1 or iy0 > iy1:
            return set()

        wx = self.bounds.min_x + (np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5) * self.cell_size
        wy = self.bounds.min_y + (np.arange(iy0, iy1 + 1, dtype=np.float64) + 0.5) * self.cell_size
        wx = wx[:, None]
        wy = wy[None, :]
        slab = self.heights[ix0 : ix1 + 1, iy0 : iy1 + 1]
        valid = slab > _OUTSIDE * 0.5

        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        xy_len_sq = dx * dx + dy * dy
        if xy_len_sq < 1e-18:
            dist = np.hypot(wx - p0[0], wy - p0[1])
            tip_z = min(p0[2], p1[2])
            z_rel = _sample_profile_z_for_radius(profile_zs, profile_rs, dist)
            cut_z = tip_z + z_rel
        else:
            # Capsule coverage in t: interval around the line projection, clipped
            # to the segment. Remaining Z is min over covering poses, not the
            # XY-closest tip (a descending ramp still covers uphill cells later).
            t_proj = ((wx - p0[0]) * dx + (wy - p0[1]) * dy) / xy_len_sq
            dist_perp_sq = (wx - (p0[0] + t_proj * dx)) ** 2 + (wy - (p0[1] + t_proj * dy)) ** 2
            r_cov = max_r + 1e-9
            delta_t = np.sqrt(np.maximum(r_cov * r_cov - dist_perp_sq, 0.0) / xy_len_sq)
            t_lo = np.maximum(t_proj - delta_t, 0.0)
            t_hi = np.minimum(t_proj + delta_t, 1.0)
            t_mid = np.clip(t_proj, 0.0, 1.0)
            in_interval = (dist_perp_sq <= r_cov * r_cov) & (t_lo <= t_hi)
            if float(np.max(profile_rs)) - float(np.min(profile_rs)) < 1e-12:
                # Cylinder: remaining Z is the lowest covering tip (z_rel constant).
                t_z = t_lo if dz >= 0.0 else t_hi
                cut_z = (p0[2] + t_z * dz) + float(profile_zs[0])
            else:
                args = (p0, dx, dy, dz, wx, wy, profile_zs, profile_rs)
                # Clamp hypot reconstruction onto the silhouette so endpoint
                # samples are not dropped (sawtooth ramps / tabs).
                cut_z = np.minimum.reduce(
                    [
                        _cut_z_along_segment(t_lo, *args, clamp_r=max_r),
                        _cut_z_along_segment(t_hi, *args, clamp_r=max_r),
                        _cut_z_along_segment(t_mid, *args, clamp_r=max_r),
                    ]
                )
            cut_z = np.where(in_interval, cut_z, np.inf)
        cut_z = np.maximum(cut_z, float(self.bounds.min_z))
        hit = valid & np.isfinite(cut_z) & (cut_z < slab)
        if not hit.any():
            return set()
        slab[hit] = np.minimum(slab[hit], cut_z[hit].astype(np.float32))
        if self._laser is not None and self._laser.clear_from_coarse_mask(
            hit,
            ix0,
            iy0,
            self.cell_size,
            self.cell_size,
            self.bounds.min_x,
            self.bounds.min_y,
        ):
            self._laser_dirty = True
        dirty = tile_keys_from_window_mask(hit, ix0, iy0, self.tile_size)
        self._touched |= dirty
        return dirty

    def _make_laser_map(self) -> LaserMap:
        nx, ny = pick_heightmap_size(self.bounds, self._laser_cell_size)
        return LaserMap.planar(self.bounds, nx, ny, self._laser_cell_size)

    def _laser_allow_from_heights(
        self,
        laser: LaserMap,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        radius: float,
        laser_z: float,
    ) -> tuple[np.ndarray | None, tuple[int, int] | None]:
        if self.heights.shape != (self.nx, self.ny):
            return None, None
        pad = radius + laser.cell_u
        iu0 = max(0, int(math.floor((min(p0[0], p1[0]) - pad - laser.origin_u) / laser.cell_u)))
        iv0 = max(0, int(math.floor((min(p0[1], p1[1]) - pad - laser.origin_v) / laser.cell_v)))
        iu1 = min(laser.nx - 1, int(math.floor((max(p0[0], p1[0]) + pad - laser.origin_u) / laser.cell_u)))
        iv1 = min(laser.nv - 1, int(math.floor((max(p0[1], p1[1]) + pad - laser.origin_v) / laser.cell_v)))
        if iu0 > iu1 or iv0 > iv1:
            return None, None
        uu = laser.origin_u + (np.arange(iu0, iu1 + 1, dtype=np.float64) + 0.5) * laser.cell_u
        vv = laser.origin_v + (np.arange(iv0, iv1 + 1, dtype=np.float64) + 0.5) * laser.cell_v
        ix = np.clip(np.floor((uu - self.bounds.min_x) / self.cell_size).astype(np.int32), 0, self.nx - 1)
        iy = np.clip(np.floor((vv - self.bounds.min_y) / self.cell_size).astype(np.int32), 0, self.ny - 1)
        slab = self.heights[ix[:, None], iy[None, :]]
        eps = max(self.cell_size, 0.2)
        allow = (slab > _OUTSIDE * 0.5) & (slab >= np.float32(laser_z - eps))
        return allow, (iu0, iv0)

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
        del tool_def, tool_unit_scale, a0, a1
        burn = laser_burn_uint8(power_s)
        if not burn:
            return False
        radius = stroke_radius_mm(self._laser_cell_size)
        laser_z = min(float(p0[2]), float(p1[2]))
        laser = self._ensure_laser()
        allow, origin = self._laser_allow_from_heights(laser, p0, p1, radius, laser_z)
        changed = laser.paint_segment(
            p0[0],
            p0[1],
            p1[0],
            p1[1],
            radius,
            allow,
            allow_origin=origin,
            burn=burn,
        )
        if changed:
            self._laser_dirty = True
        elif self._laser is not None and not np.any(self._laser.intensity):
            # First paint missed (air); drop so mill stays on the fast path.
            self._drop_laser()
        return changed

    def snapshot_full(self) -> object:
        return self._snapshot_with_laser(("full", compress_array(self.heights)), full=True)

    def snapshot_changed(self, keys: set[TileKey]) -> object:
        ts = self.tile_size
        tiles: dict[TileKey, np.ndarray] = {}
        for key in keys:
            tx, ty, _tz = key
            x0, y0 = tx * ts, ty * ts
            x1, y1 = min(self.nx, x0 + ts), min(self.ny, y0 + ts)
            tiles[key] = self.heights[x0:x1, y0:y1].copy()
        return self._snapshot_with_laser(("delta", tiles), full=False)

    def restore(self, payload: object) -> set[TileKey]:
        occ, laser_payload = split_laser_snapshot(payload)
        kind, data = occ  # type: ignore[misc]
        if kind == "full":
            self.heights[:, :] = decompress_array(data)
            self._touched = self._tiles_not_at_seed()
            self._restore_laser_payload(laser_payload, occupancy_kind=kind)
            return self.initial_surface_keys()
        dirty: set[TileKey] = set()
        ts = self.tile_size
        for key, tile in data.items():
            tx, ty, _tz = key
            x0, y0 = tx * ts, ty * ts
            x1, y1 = x0 + tile.shape[0], y0 + tile.shape[1]
            self.heights[x0:x1, y0:y1] = tile
            dirty.add(key)
        self._touched |= dirty
        self._restore_laser_payload(laser_payload, occupancy_kind=kind)
        return dirty

    def copy_tiles(self, keys: set[TileKey]) -> HeightmapBackend:
        ts = self.tile_size
        if not keys:
            return HeightmapBackend(
                self.bounds,
                self.cell_size,
                self.shape,
                self.tile_size,
                heights=np.empty((0, 0), dtype=np.float32),
                seed=False,
                index_origin=(0, 0),
                laser_cell_size_mm=self._laser_cell_size,
            )
        txs = [k[0] for k in keys]
        tys = [k[1] for k in keys]
        x0 = max(0, min(txs) * ts)
        y0 = max(0, min(tys) * ts)
        x1 = min(self.nx, (max(txs) + 1) * ts)
        y1 = min(self.ny, (max(tys) + 1) * ts)
        return HeightmapBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.tile_size,
            heights=self._read_patch(x0, y0, x1, y1),
            seed=False,
            index_origin=(x0, y0),
            laser_cell_size_mm=self._laser_cell_size,
        )

    def expand_dirty(self, dirty: set[TileKey]) -> set[TileKey]:
        expanded = set(dirty)
        for tx, ty, _tz in dirty:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    x, y = tx + dx, ty + dy
                    if 0 <= x < self.n_tiles_x and 0 <= y < self.n_tiles_y:
                        expanded.add((x, y, 0))
        return expanded

    def initial_surface_keys(self) -> set[TileKey]:
        return {(tx, ty, 0) for tx in range(self.n_tiles_x) for ty in range(self.n_tiles_y)}

    def all_non_full_keys(self) -> set[TileKey]:
        return set(self._touched)

    def _tiles_not_at_seed(self) -> set[TileKey]:
        if self.heights.shape != (self.nx, self.ny):
            return set(self._touched)
        seed = np.empty_like(self.heights)
        self._fill_seed(seed)
        valid = self.heights > _OUTSIDE * 0.5
        seed_valid = seed > _OUTSIDE * 0.5
        mask = (valid != seed_valid) | (valid & (np.abs(self.heights - seed) > 1e-4))
        return tile_keys_from_window_mask(mask, 0, 0, self.tile_size)

    def mesh_tiles(self, keys: set[TileKey]) -> dict[TileKey, tuple | None]:
        """GPU meshes for requested tiles (vectorized; one draw per tile)."""
        if not keys or self.heights.size == 0:
            return {(0, 0, 0): None} if keys else {}
        ts = self.tile_size
        out: dict[TileKey, tuple | None] = {}
        for key in keys:
            tx, ty, tz = key
            if tz != 0:
                continue
            x0, y0 = tx * ts, ty * ts
            packed = _mesh_heightmap_region(
                self,
                x0,
                y0,
                min(self.nx, x0 + ts),
                min(self.ny, y0 + ts),
            )
            out[key] = packed[0] if packed else None
            for extra_i, item in enumerate(packed[1:], start=1):
                out[(tx, ty, extra_i)] = item
        return out

    def hud_stats(self) -> dict:
        return {
            "carver": self.kind,
            "cell_size_mm": float(self.cell_size),
            "grid_nx": int(self.nx),
            "grid_ny": int(self.ny),
            "grid_nz": 1,
        }

    @staticmethod
    def create_checkpoint_store(slot_count: int):
        return ArrayCheckpointStore(slot_count=slot_count)

    @staticmethod
    def restore_checkpoint(store, checkpoint, backend) -> set:
        return restore_array_checkpoint(backend, store, checkpoint)

    def height_at_world(self, x: float, y: float) -> float | None:
        """Top Z at world XY, or None if outside / empty."""
        ix = int(math.floor((x - self.bounds.min_x) / self.cell_size))
        iy = int(math.floor((y - self.bounds.min_y) / self.cell_size))
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return None
        h = float(self._read_cell(ix, iy))
        if h < _OUTSIDE * 0.5:
            return None
        return h

    def _read_cell(self, ix: int, iy: int) -> np.float32:
        lx = ix - self._ox
        ly = iy - self._oy
        h = self.heights
        if lx < 0 or ly < 0 or lx >= h.shape[0] or ly >= h.shape[1]:
            return _OUTSIDE
        return h[lx, ly]

    def _read_patch(self, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        rows = max(0, x1 - x0)
        cols = max(0, y1 - y0)
        if rows == 0 or cols == 0:
            return np.empty((rows, cols), dtype=np.float32)
        sx0, sy0 = self._ox, self._oy
        sx1 = sx0 + self.heights.shape[0]
        sy1 = sy0 + self.heights.shape[1]
        if x0 >= sx0 and y0 >= sy0 and x1 <= sx1 and y1 <= sy1:
            return self.heights[x0 - sx0 : x1 - sx0, y0 - sy0 : y1 - sy0]
        out = np.full((rows, cols), _OUTSIDE, dtype=np.float32)
        ix0, iy0 = max(x0, sx0), max(y0, sy0)
        ix1, iy1 = min(x1, sx1), min(y1, sy1)
        if ix0 >= ix1 or iy0 >= iy1:
            return out
        out[ix0 - x0 : ix1 - x0, iy0 - y0 : iy1 - y0] = self.heights[ix0 - sx0 : ix1 - sx0, iy0 - sy0 : iy1 - sy0]
        return out
