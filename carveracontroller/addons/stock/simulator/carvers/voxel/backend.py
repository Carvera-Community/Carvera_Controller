"""Voxel carver backend wrapping the existing chunked occupancy grid."""

from __future__ import annotations

import itertools
import math

import numpy as np

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.array_mesh import aabb_box_mesh, coalesce_indexed_meshes
from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, CarverBackend, TileKey
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LaserDecalMixin,
    LaserMap,
    laser_burn_uint8,
    pick_laser_cell_size_mm,
    split_laser_snapshot,
    stroke_parts,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds, stock_theta_deg
from carveracontroller.addons.stock.stock_shape import RectangularStock, StockShape

from .checkpoints import CheckpointStore, restore_voxel_checkpoint
from .grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord, ChunkedVoxelGrid
from .mesher import mesh_dirty_chunks
from .occupancy import expand_dirty_with_neighbors, exterior_chunk_keys, non_full_chunk_keys, seed_shape_occupancy

# Chunks per coalesced draw. Eight 16³ chunks usually fit in one draw; when exposed faces
# exceed a GLES Mesh cap (65535 indices / vertex values), the bin is split into extra draws.
VOXEL_MESH_BIN = 2
# Part k>0 of bin (sx, sy, sz) is drawn at (sx, sy, sz + k * stride). Bin indices
# stay far below this, so the extra draw does not collide with another bin.
VOXEL_MESH_PART_STRIDE = 1024


def voxel_draw_key(bin_key: tuple[int, int, int], part: int) -> tuple[int, int, int]:
    """GPU key for one uint16 split of a super-chunk."""
    sx, sy, sz = bin_key
    if part <= 0:
        return (int(sx), int(sy), int(sz))
    return (int(sx), int(sy), int(sz) + int(part) * VOXEL_MESH_PART_STRIDE)


def _voxel_draw_bin(key: tuple[int, int, int]) -> tuple[tuple[int, int, int], int]:
    sx, sy, z = (int(key[0]), int(key[1]), int(key[2]))
    part = z // VOXEL_MESH_PART_STRIDE if z >= VOXEL_MESH_PART_STRIDE else 0
    return (sx, sy, z - part * VOXEL_MESH_PART_STRIDE), part


def retire_voxel_draw_keys(meshes: dict, part_count: dict[tuple[int, int, int], int]) -> None:
    """Tombstone overflow draws when a bin now fits in fewer parts.

    ``part_count`` maps a bin ``(sx, sy, sz)`` to how many draws the viewer
    still holds. Bins absent from ``meshes`` are left alone.
    """
    seen: dict[tuple[int, int, int], int] = {}
    for key, packed in list(meshes.items()):
        if not isinstance(key, tuple) or len(key) != 3:
            continue
        base, part = _voxel_draw_bin(key)
        if packed is None and part == 0:
            seen[base] = -1
            continue
        if packed is None:
            continue
        seen[base] = max(seen.get(base, -1), part)
    for base, last in seen.items():
        prev = part_count.get(base, 0)
        keep = 0 if last < 0 else last + 1
        for part in range(keep, prev):
            meshes[voxel_draw_key(base, part)] = None
        if keep:
            part_count[base] = keep
        else:
            part_count.pop(base, None)


class VoxelBackend(LaserDecalMixin):
    """3D voxel occupancy — accurate for undercuts and arbitrary kinematics."""

    kind = "voxel"

    def __init__(
        self,
        bounds: StockBounds,
        cell_size_mm: float,
        shape: StockShape | None = None,
        chunk_size: int = DEFAULT_TILE_SIZE,
        *,
        grid: ChunkedVoxelGrid | None = None,
        seed: bool = True,
        has_4axis: bool = False,
        laser_cell_size_mm: float | None = None,
    ):
        self.bounds = bounds
        self.cell_size = float(cell_size_mm)
        self.chunk_size = int(chunk_size)
        self.shape: StockShape = shape or RectangularStock(
            width_mm=max(bounds.size[0], 1e-6),
            length_mm=max(bounds.size[1], 1e-6),
            height_mm=max(bounds.size[2], 1e-6),
        )
        self.has_4axis = bool(has_4axis)
        self._laser_cell_size = (
            float(laser_cell_size_mm)
            if laser_cell_size_mm is not None
            else pick_laser_cell_size_mm(bounds, self.cell_size, cylindrical=self.has_4axis)
        )
        self.grid = grid if grid is not None else ChunkedVoxelGrid(bounds, cell_size_mm, chunk_size)
        if seed and grid is None:
            seed_shape_occupancy(self.grid, self.shape)
        self._init_laser()

    @property
    def voxel_size(self) -> float:
        return self.cell_size

    def reset_occupancy(self) -> set[TileKey]:
        self.grid.reset()
        seed_shape_occupancy(self.grid, self.shape)
        self._drop_laser()
        return self.initial_surface_keys()

    def clone_empty(self) -> VoxelBackend:
        return VoxelBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.chunk_size,
            seed=True,
            has_4axis=self.has_4axis,
            laser_cell_size_mm=self._laser_cell_size,
        )

    def _make_laser_map(self) -> LaserMap:
        if self.has_4axis:
            from carveracontroller.addons.stock.simulator.carvers.cylindrical.backend import pick_cylindrical_dims

            diameter = min(self.bounds.size[1], self.bounds.size[2])
            nx, n_theta, d_theta = pick_cylindrical_dims(self.bounds, self._laser_cell_size, diameter)
            return LaserMap.cylindrical(self.bounds, nx, n_theta, self._laser_cell_size, d_theta)
        from carveracontroller.addons.stock.simulator.carvers.heightmap.backend import pick_heightmap_size

        nx, ny = pick_heightmap_size(self.bounds, self._laser_cell_size)
        return LaserMap.planar(self.bounds, nx, ny, self._laser_cell_size)

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
        return self.carve_segments([(p0, p1, a0, a1)], profile, tool_unit_scale=tool_unit_scale, tool_def=tool_def)

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
        from carveracontroller.addons.stock.simulator.native import carve_voxels

        dirty = carve_voxels(self.grid, list(segments), profile, volumes=volumes)
        if self._laser is not None:
            max_r = max((r for _z, r in profile), default=0.0)
            if max_r > 0 and self._clear_laser_batch(segments, max_r):
                self._laser_dirty = True
        return dirty

    def _clear_laser_batch(self, segments, radius: float) -> bool:
        laser = self._laser
        if laser is None or not segments:
            return False
        from carveracontroller.addons.stock.simulator.native import clear_laser_capsules

        u0: list[float] = []
        v0: list[float] = []
        u1: list[float] = []
        v1: list[float] = []
        cylindrical = laser.mode == "cylindrical"
        for p0, p1, a0, a1 in segments:
            if cylindrical:
                u0.append(float(p0[0]))
                v0.append(self._stock_theta(p0, a0))
                u1.append(float(p1[0]))
                v1.append(self._stock_theta(p1, a1))
            else:
                u0.append(float(p0[0]))
                v0.append(float(p0[1]))
                u1.append(float(p1[0]))
                v1.append(float(p1[1]))
        return clear_laser_capsules(
            laser.intensity,
            u0,
            v0,
            u1,
            v1,
            float(radius),
            cell_u=laser.cell_u,
            cell_v=laser.cell_v,
            origin_u=laser.origin_u,
            origin_v=laser.origin_v,
            wrap_v=laser.wrap_v,
            v_period=laser.v_period,
            v_scale=laser.v_scale,
            dirty=laser.dirty_native_args(),
        )

    def _axis_yz(self) -> tuple[float, float]:
        return (
            0.5 * (self.bounds.min_y + self.bounds.max_y),
            0.5 * (self.bounds.min_z + self.bounds.max_z),
        )

    def _stock_theta(self, p: tuple[float, float, float], angle_deg: float) -> float:
        ay, az = self._axis_yz()
        return stock_theta_deg(p[1], p[2], angle_deg, ay, az)

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
        laser = self._ensure_laser()
        allow, origin = self._laser_allow_mask(laser, p0, p1, a0, a1, radius)
        if laser.mode == "cylindrical":
            changed = laser.paint_segment(
                p0[0],
                self._stock_theta(p0, a0),
                p1[0],
                self._stock_theta(p1, a1),
                radius,
                allow,
                allow_origin=origin,
                burn=burn,
            )
        else:
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
            self._drop_laser()
        return changed

    def engrave_segments(self, jobs, tool_unit_scale: float = 1.0) -> bool:
        changed = False
        for item in jobs:
            p0, p1, a0, a1, power = stroke_parts(item)
            if self.engrave_segment(p0, p1, None, tool_unit_scale, a0=a0, a1=a1, power_s=power):
                changed = True
        return changed

    def _sample_solid_world(self, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray) -> np.ndarray:
        """Vectorized occupancy sample matching ``ChunkedVoxelGrid.is_solid_at_world``."""
        out = np.zeros(xs.shape, dtype=bool)
        b = self.bounds
        valid = (b.min_x <= xs) & (xs < b.max_x) & (b.min_y <= ys) & (ys < b.max_y) & (b.min_z <= zs) & (zs < b.max_z)
        if not np.any(valid):
            return out
        vox = max(float(self.cell_size), 1e-12)
        ix = np.floor((xs - b.min_x) / vox).astype(np.int32)
        iy = np.floor((ys - b.min_y) / vox).astype(np.int32)
        iz = np.floor((zs - b.min_z) / vox).astype(np.int32)
        in_grid = (
            valid & (ix >= 0) & (ix < self.grid.nx) & (iy >= 0) & (iy < self.grid.ny) & (iz >= 0) & (iz < self.grid.nz)
        )
        if not np.any(in_grid):
            return out
        cs = int(self.grid.chunk_size)
        cx = ix // cs
        cy = iy // cs
        cz = iz // cs
        # Flatten chunk ids for grouping; stroke windows almost always hit one chunk.
        chunk_id = (cx.astype(np.int64) * 1_000_003 + cy.astype(np.int64)) * 1_000_003 + cz.astype(np.int64)
        flat = np.flatnonzero(in_grid)
        ids = chunk_id.ravel()[flat]
        order = np.argsort(ids, kind="mergesort")
        flat = flat[order]
        ids = ids[order]
        starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
        ends = np.r_[starts[1:], ids.size]
        for s, e in zip(starts.tolist(), ends.tolist()):
            idx = flat[s:e]
            i0 = int(ix.ravel()[idx[0]])
            j0 = int(iy.ravel()[idx[0]])
            k0 = int(iz.ravel()[idx[0]])
            coord = self.grid.chunk_of_voxel(i0, j0, k0)
            state = self.grid.get_chunk_state(coord)
            if state is CHUNK_FULL:
                out.ravel()[idx] = True
                continue
            if state is CHUNK_EMPTY:
                continue
            lx = ix.ravel()[idx] - coord.cx * cs
            ly = iy.ravel()[idx] - coord.cy * cs
            lz = iz.ravel()[idx] - coord.cz * cs
            out.ravel()[idx] = state[lx, ly, lz].astype(bool, copy=False)  # type: ignore[index]
        return out

    def _stock_under_laser_xy(self, x: float, y: float, z_laser: float) -> bool:
        """True if remaining stock sits at/just under the beam (top plane is exclusive max_z)."""
        b = self.bounds
        if not (b.min_x <= x < b.max_x and b.min_y <= y < b.max_y):
            return False
        z_hi = min(float(z_laser), b.max_z - 1e-6)
        z_hi = max(z_hi, b.min_z)
        if self.grid.is_solid_at_world(x, y, z_hi):
            return True
        z_in = max(z_hi - 0.51 * self.cell_size, b.min_z + 1e-6)
        return self.grid.is_solid_at_world(x, y, z_in)

    def _stock_under_laser_xy_grid(self, x: np.ndarray, y: np.ndarray, z_laser: float) -> np.ndarray:
        """Vectorized planar stock test for a laser allow window."""
        b = self.bounds
        allow = np.zeros(x.shape, dtype=np.uint8)
        in_xy = (b.min_x <= x) & (x < b.max_x) & (b.min_y <= y) & (y < b.max_y)
        if not np.any(in_xy):
            return allow
        z_hi = min(float(z_laser), b.max_z - 1e-6)
        z_hi = max(z_hi, b.min_z)
        z_hi_a = np.full(x.shape, z_hi, dtype=np.float64)
        solid = self._sample_solid_world(x, y, z_hi_a)
        z_in = max(z_hi - 0.51 * self.cell_size, b.min_z + 1e-6)
        if z_in < z_hi - 1e-12:
            need = in_xy & ~solid
            if np.any(need):
                solid = solid | self._sample_solid_world(x, y, np.full(x.shape, z_in, dtype=np.float64))
        allow[in_xy & solid] = 1
        return allow

    def _laser_allow_mask(
        self,
        laser: LaserMap,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        a0: float,
        a1: float,
        radius: float,
    ) -> tuple[np.ndarray, tuple[int, int]]:
        """Uint8 allow window whose [0,0] is laser index (iu0, iv0)."""
        z_mid = 0.5 * (p0[2] + p1[2])
        axis_y, axis_z = self._axis_yz()
        pad = radius + laser.cell_u
        iu0 = max(0, int(math.floor((min(p0[0], p1[0]) - pad - laser.origin_u) / laser.cell_u)))
        iu1 = min(laser.nx - 1, int(math.floor((max(p0[0], p1[0]) + pad - laser.origin_u) / laser.cell_u)))
        if iu0 > iu1:
            return np.zeros((0, 0), dtype=np.uint8), (0, 0)
        probe_r = min(
            0.5 * min(self.bounds.size[1], self.bounds.size[2]),
            math.hypot(p0[1] - axis_y, p0[2] - axis_z),
        )
        probe_r = max(0.0, probe_r - 0.51 * self.cell_size)
        rows = iu1 - iu0 + 1
        uu = laser.origin_u + (np.arange(iu0, iu1 + 1, dtype=np.float64) + 0.5) * laser.cell_u
        if laser.wrap_v:
            pad_v = radius / max(laser.v_scale, 1e-12) + laser.cell_v
            iv_idx = laser._wrapped_v_indices(
                self._stock_theta(p0, a0),
                self._stock_theta(p1, a1),
                pad_v,
            )
            # Contiguous window in laser index space; wrap spans use the full θ ring.
            iv_unique = np.unique(iv_idx.astype(np.int32) % laser.nv)
            if iv_unique.size == 0:
                return np.zeros((rows, 0), dtype=np.uint8), (iu0, 0)
            iv0 = int(iv_unique.min())
            iv1 = int(iv_unique.max())
            if iv1 - iv0 + 1 == int(iv_unique.size):
                cols = iv1 - iv0 + 1
                ivs = np.arange(iv0, iv1 + 1, dtype=np.int32)
            else:
                iv0 = 0
                cols = laser.nv
                ivs = np.arange(laser.nv, dtype=np.int32)
            allow = np.zeros((rows, cols), dtype=np.uint8)
            selected = np.zeros(laser.nv, dtype=bool)
            selected[iv_unique] = True
            use = selected[ivs]
            if not np.any(use):
                return allow, (iu0, iv0)
            ang = np.radians((ivs.astype(np.float64) + 0.5) * laser.cell_v)
            ys = axis_y + np.sin(ang) * probe_r
            zs = axis_z + np.cos(ang) * probe_r
            X = np.broadcast_to(uu[:, None], (rows, cols))
            Y = np.broadcast_to(ys[None, :], (rows, cols))
            Z = np.broadcast_to(zs[None, :], (rows, cols))
            solid = self._sample_solid_world(X, Y, Z)
            allow[:, use] = solid[:, use].astype(np.uint8, copy=False)
            return np.ascontiguousarray(allow), (iu0, iv0)

        iv0 = max(0, int(math.floor((min(p0[1], p1[1]) - pad - laser.origin_v) / laser.cell_v)))
        iv1 = min(laser.nv - 1, int(math.floor((max(p0[1], p1[1]) + pad - laser.origin_v) / laser.cell_v)))
        if iv0 > iv1:
            return np.zeros((rows, 0), dtype=np.uint8), (iu0, 0)
        vv = laser.origin_v + (np.arange(iv0, iv1 + 1, dtype=np.float64) + 0.5) * laser.cell_v
        X, Y = np.meshgrid(uu, vv, indexing="ij")
        allow = self._stock_under_laser_xy_grid(X, Y, z_mid)
        return np.ascontiguousarray(allow), (iu0, iv0)

    def snapshot_full(self) -> object:
        raw, _nbytes = self.grid.snapshot_non_full()
        return self._snapshot_with_laser(("full", raw), full=True)

    def snapshot_changed(self, keys: set[TileKey]) -> object:
        delta: dict[TileKey, object] = {}
        for key in keys:
            state = self.grid.get_chunk_state(ChunkCoord(*key))
            if state is CHUNK_FULL:
                delta[key] = CHUNK_FULL
            elif state is CHUNK_EMPTY:
                delta[key] = CHUNK_EMPTY
            elif isinstance(state, object) and hasattr(state, "copy"):
                delta[key] = state.copy()
            else:
                delta[key] = state
        return self._snapshot_with_laser(("delta", delta), full=False)

    def restore(self, payload: object) -> set[TileKey]:
        occ, laser_payload = split_laser_snapshot(payload)
        kind, data = occ  # type: ignore[misc]
        if kind == "full":
            self.grid.restore_non_full(data)
            self._restore_laser_payload(laser_payload, occupancy_kind=kind)
            return set(data.keys()) | self.initial_surface_keys()
        for key, state in data.items():
            if state is CHUNK_FULL:
                self.grid._chunks.pop(key, None)
            elif state is CHUNK_EMPTY:
                self.grid._chunks[key] = CHUNK_EMPTY
            else:
                self.grid._chunks[key] = state.copy() if hasattr(state, "copy") else state
        self._restore_laser_payload(laser_payload, occupancy_kind=kind)
        return set(data.keys())

    def copy_tiles(self, keys: set[TileKey]) -> VoxelBackend:
        copied = self.grid.copy_chunks(keys)
        return VoxelBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.chunk_size,
            grid=copied,
            seed=False,
            has_4axis=self.has_4axis,
            laser_cell_size_mm=self._laser_cell_size,
        )

    def uniform_shell(self) -> bool:
        """True when every chunk is still implicit solid and the stock is a box."""
        if not isinstance(self.shape, RectangularStock):
            return False
        return not non_full_chunk_keys(self.grid)

    def expand_mesh_bins(self, keys: set[TileKey]) -> set[TileKey]:
        """Every chunk of each super-chunk touched by ``keys``."""
        grid = self.grid
        out: set[TileKey] = set()
        for cx, cy, cz in keys:
            sx = (int(cx) // VOXEL_MESH_BIN) * VOXEL_MESH_BIN
            sy = (int(cy) // VOXEL_MESH_BIN) * VOXEL_MESH_BIN
            sz = (int(cz) // VOXEL_MESH_BIN) * VOXEL_MESH_BIN
            for dx in range(VOXEL_MESH_BIN):
                for dy in range(VOXEL_MESH_BIN):
                    for dz in range(VOXEL_MESH_BIN):
                        x, y, z = sx + dx, sy + dy, sz + dz
                        if 0 <= x < grid.n_chunks_x and 0 <= y < grid.n_chunks_y and 0 <= z < grid.n_chunks_z:
                            out.add((x, y, z))
        return out

    def mesh_tiles(self, keys: set[TileKey], *, uniform: bool | None = None) -> dict[TileKey, tuple | None]:
        """One draw per super-chunk, or a single box while the stock is uncut."""
        if not keys:
            return {}
        if uniform is None:
            uniform = self.uniform_shell()
        if uniform:
            grid = self.grid
            vs = float(grid.voxel_size)
            bounds = grid.bounds
            box = aabb_box_mesh(
                float(bounds.min_x),
                float(bounds.min_y),
                float(bounds.min_z),
                float(bounds.min_x) + grid.nx * vs,
                float(bounds.min_y) + grid.ny * vs,
                float(bounds.min_z) + grid.nz * vs,
            )
            return {(0, 0, 0): box}
        groups: dict[tuple[int, int, int], list[TileKey]] = {}
        grid = self.grid
        for key in keys:
            cx, cy, cz = int(key[0]), int(key[1]), int(key[2])
            if not (0 <= cx < grid.n_chunks_x and 0 <= cy < grid.n_chunks_y and 0 <= cz < grid.n_chunks_z):
                continue
            bin_key = (cx // VOXEL_MESH_BIN, cy // VOXEL_MESH_BIN, cz // VOXEL_MESH_BIN)
            groups.setdefault(bin_key, []).append((cx, cy, cz))
        out: dict[TileKey, tuple | None] = {}
        for bin_key in sorted(groups):
            chunk_keys = sorted(groups[bin_key])
            partial = mesh_dirty_chunks(grid, set(chunk_keys))
            coalesced = coalesce_indexed_meshes(
                itertools.chain.from_iterable(partial[key] for key in chunk_keys if key in partial)
            )
            if not coalesced:
                out[bin_key] = None
                continue
            for part, item in enumerate(coalesced):
                out[voxel_draw_key(bin_key, part)] = item
        return out

    def expand_dirty(self, dirty: set[TileKey]) -> set[TileKey]:
        return expand_dirty_with_neighbors(self.grid, dirty)

    def initial_surface_keys(self) -> set[TileKey]:
        dirty = exterior_chunk_keys(self.grid)
        dirty.update(non_full_chunk_keys(self.grid))
        return dirty

    def all_non_full_keys(self) -> set[TileKey]:
        return non_full_chunk_keys(self.grid)

    def hud_stats(self) -> dict:
        g = self.grid
        return {
            "carver": self.kind,
            "cell_size_mm": float(g.voxel_size),
            "grid_nx": int(g.nx),
            "grid_ny": int(g.ny),
            "grid_nz": int(g.nz),
        }

    @staticmethod
    def create_checkpoint_store(slot_count: int):
        """Voxel bit-packed chunk checkpoints (defined next to the grid carver)."""
        return CheckpointStore(slot_count=slot_count)

    @staticmethod
    def restore_checkpoint(store, checkpoint, backend) -> set:
        return restore_voxel_checkpoint(backend, store, checkpoint)


# Satisfy the protocol for type checkers.
_: type[CarverBackend] = VoxelBackend  # type: ignore[misc,assignment]
