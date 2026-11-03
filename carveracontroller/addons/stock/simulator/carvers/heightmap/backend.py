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
    aabb_box_mesh,
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
    stroke_parts,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import (
    CylindricalStock,
    RectangularStock,
    RotaryCylindricalStock,
    StockShape,
)

# Cells per coalesced draw. A 64×64 block stays small enough to split quickly when a
# carved surface exceeds the GLES index-list cap (65535), which is tighter than the
# uint16 vertex cap once skirts stop sharing vertices.
HEIGHTMAP_MESH_BIN = 64


def pick_heightmap_size(bounds: StockBounds, cell_size_mm: float) -> tuple[int, int]:
    sx, sy, _sz = bounds.size
    nx = max(1, int(math.ceil(sx / max(cell_size_mm, 1e-9))))
    ny = max(1, int(math.ceil(sy / max(cell_size_mm, 1e-9))))
    return nx, ny


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
        profile=None,
    ) -> set[TileKey]:
        if profile is None:
            profile = resolve_cutting_profile(tool_def, tool_unit_scale=tool_unit_scale)
        return self.carve_segments([(p0, p1, a0, a1)], profile, tool_unit_scale=tool_unit_scale)

    def carve_segments(
        self,
        segments,
        profile,
        tool_unit_scale: float = 1.0,
        tool_def=None,
        volumes=None,
    ) -> set[TileKey]:
        del tool_unit_scale, tool_def
        if not segments or not profile:
            return set()
        if self.heights.shape != (self.nx, self.ny) or self._ox != 0 or self._oy != 0:
            raise RuntimeError("heightmap carve requires the full occupancy grid")
        from carveracontroller.addons.stock.simulator.native import carve_heightmap

        laser = self._laser
        dirty, laser_changed = carve_heightmap(
            self.heights,
            min_x=float(self.bounds.min_x),
            min_y=float(self.bounds.min_y),
            min_z=float(self.bounds.min_z),
            cell=float(self.cell_size),
            tile=int(self.tile_size),
            segments=list(segments),
            profile=profile,
            laser=None if laser is None else laser.intensity,
            laser_cell_u=0.0 if laser is None else laser.cell_u,
            laser_cell_v=0.0 if laser is None else laser.cell_v,
            laser_origin_u=0.0 if laser is None else laser.origin_u,
            laser_origin_v=0.0 if laser is None else laser.origin_v,
            laser_dirty=None if laser is None else laser.dirty_native_args(),
            volumes=volumes,
        )
        if laser_changed:
            self._laser_dirty = True
        self._touched |= dirty
        return dirty

    def _make_laser_map(self) -> LaserMap:
        nx, ny = pick_heightmap_size(self.bounds, self._laser_cell_size)
        return LaserMap.planar(self.bounds, nx, ny, self._laser_cell_size)

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
        return self.engrave_segments([(p0, p1, 0.0, 0.0, power_s)])

    def engrave_segments(self, jobs, tool_unit_scale: float = 1.0) -> bool:
        """Paint laser strokes without merging them. ``jobs`` are ``(p0, p1, a0, a1, power)`` or CarveJobs."""
        del tool_unit_scale
        u0: list[float] = []
        v0: list[float] = []
        u1: list[float] = []
        v1: list[float] = []
        burns: list[int] = []
        laser_z: list[float] = []
        for item in jobs:
            p0, p1, _a0, _a1, power = stroke_parts(item)
            burn = int(laser_burn_uint8(power))
            if not burn:
                continue
            u0.append(float(p0[0]))
            v0.append(float(p0[1]))
            u1.append(float(p1[0]))
            v1.append(float(p1[1]))
            burns.append(burn)
            laser_z.append(min(float(p0[2]), float(p1[2])))
        if not burns:
            return False
        from carveracontroller.addons.stock.simulator.native import paint_laser

        laser = self._ensure_laser()
        changed = paint_laser(
            laser.intensity,
            u0,
            v0,
            u1,
            v1,
            burns,
            stroke_radius_mm(self._laser_cell_size),
            cell_u=laser.cell_u,
            cell_v=laser.cell_v,
            origin_u=laser.origin_u,
            origin_v=laser.origin_v,
            wrap_v=False,
            v_scale=laser.v_scale,
            occ_kind=1,
            occ=self.heights,
            occ_min_x=float(self.bounds.min_x),
            occ_min_y=float(self.bounds.min_y),
            occ_cell=float(self.cell_size),
            z_or_r=laser_z,
            dirty=laser.dirty_native_args(),
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

    def uniform_shell(self) -> bool:
        """True when the live field is an uncut rectangular block.

        A partial ``copy_tiles`` window can look flat even after a pocket, so the
        worker passes this flag from the live backend instead of trusting a copy.
        """
        if not isinstance(self.shape, RectangularStock):
            return False
        if self._ox != 0 or self._oy != 0:
            return False
        heights = self.heights
        if heights.shape != (self.nx, self.ny) or heights.size == 0:
            return False
        top = np.float32(self.bounds.max_z)
        return bool(np.max(np.abs(heights - top)) <= np.float32(1e-4))

    def expand_mesh_bins(self, keys: set[TileKey]) -> set[TileKey]:
        """Tile keys covering every mesh bin touched by ``keys``.

        A bin is meshed as a whole so the draw key stays put while the tool moves
        inside it. The caller still expands one more ring for the height halo.
        """
        ts = self.tile_size
        bins: set[tuple[int, int]] = set()
        for tx, ty, tz in keys:
            if tz != 0:
                continue
            x_lo = tx * ts
            y_lo = ty * ts
            x_hi = min(self.nx, x_lo + ts) - 1
            y_hi = min(self.ny, y_lo + ts) - 1
            if x_hi < x_lo or y_hi < y_lo:
                continue
            for bx in range(x_lo // HEIGHTMAP_MESH_BIN, x_hi // HEIGHTMAP_MESH_BIN + 1):
                for by in range(y_lo // HEIGHTMAP_MESH_BIN, y_hi // HEIGHTMAP_MESH_BIN + 1):
                    bins.add((bx, by))
        out: set[TileKey] = set()
        for bx, by in bins:
            cell_x0 = bx * HEIGHTMAP_MESH_BIN
            cell_y0 = by * HEIGHTMAP_MESH_BIN
            cell_x1 = min(self.nx, cell_x0 + HEIGHTMAP_MESH_BIN) - 1
            cell_y1 = min(self.ny, cell_y0 + HEIGHTMAP_MESH_BIN) - 1
            for tx in range(cell_x0 // ts, cell_x1 // ts + 1):
                for ty in range(cell_y0 // ts, cell_y1 // ts + 1):
                    if 0 <= tx < self.n_tiles_x and 0 <= ty < self.n_tiles_y:
                        out.add((tx, ty, 0))
        return out

    def _bins_for_tile_keys(self, keys: set[TileKey]) -> set[tuple[int, int]]:
        ts = self.tile_size
        bins: set[tuple[int, int]] = set()
        for tx, ty, tz in keys:
            if tz != 0:
                continue
            x_lo = tx * ts
            y_lo = ty * ts
            x_hi = min(self.nx, x_lo + ts) - 1
            y_hi = min(self.ny, y_lo + ts) - 1
            if x_hi < x_lo or y_hi < y_lo:
                continue
            for bx in range(x_lo // HEIGHTMAP_MESH_BIN, x_hi // HEIGHTMAP_MESH_BIN + 1):
                for by in range(y_lo // HEIGHTMAP_MESH_BIN, y_hi // HEIGHTMAP_MESH_BIN + 1):
                    bins.add((bx, by))
        return bins

    def mesh_tiles(self, keys: set[TileKey], *, uniform: bool | None = None) -> dict[TileKey, tuple | None]:
        """GPU meshes for the bins covering ``keys``.

        An uncut rectangle is one box at ``(0, 0, 0)``. Carved stock is one welded
        mesh per ``HEIGHTMAP_MESH_BIN`` block, split only if a block exceeds the
        uint16 vertex cap.
        """
        if not keys or self.heights.size == 0:
            return {(0, 0, 0): None} if keys else {}
        if uniform is None:
            uniform = self.uniform_shell()
        if uniform:
            bounds = self.bounds
            vs = float(self.cell_size)
            box = aabb_box_mesh(
                float(bounds.min_x),
                float(bounds.min_y),
                float(bounds.min_z),
                float(bounds.min_x) + self.nx * vs,
                float(bounds.min_y) + self.ny * vs,
                float(bounds.max_z),
            )
            return {(0, 0, 0): box}
        out: dict[TileKey, tuple | None] = {}
        for bx, by in sorted(self._bins_for_tile_keys(keys)):
            x0 = bx * HEIGHTMAP_MESH_BIN
            y0 = by * HEIGHTMAP_MESH_BIN
            x1 = min(self.nx, x0 + HEIGHTMAP_MESH_BIN)
            y1 = min(self.ny, y0 + HEIGHTMAP_MESH_BIN)
            packed = _mesh_heightmap_region(self, x0, y0, x1, y1)
            if not packed:
                out[(bx, by, 0)] = None
                continue
            for part, item in enumerate(packed):
                out[(bx, by, part)] = item
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
