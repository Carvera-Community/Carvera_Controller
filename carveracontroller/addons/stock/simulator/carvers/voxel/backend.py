"""Voxel carver backend wrapping the existing chunked occupancy grid."""

from __future__ import annotations

import math

import numpy as np

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, CarverBackend, TileKey
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LaserDecalMixin,
    LaserMap,
    laser_burn_uint8,
    pick_laser_cell_size_mm,
    split_laser_snapshot,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds, stock_theta_deg
from carveracontroller.addons.stock.stock_shape import RectangularStock, StockShape

from .carve import carve_segment_into_grid
from .checkpoints import CheckpointStore, restore_voxel_checkpoint
from .grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord, ChunkedVoxelGrid
from .mesher import mesh_dirty_chunks
from .occupancy import expand_dirty_with_neighbors, exterior_chunk_keys, non_full_chunk_keys, seed_shape_occupancy


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
    ) -> set[TileKey]:
        dirty = carve_segment_into_grid(
            self.grid,
            p0,
            p1,
            tool_def,
            tool_unit_scale=tool_unit_scale,
            a0=a0,
            a1=a1,
        )
        if self._laser is not None:
            profile = resolve_cutting_profile(tool_def, tool_unit_scale=tool_unit_scale)
            max_r = max((r for _z, r in profile), default=0.0) if profile else 0.0
            if max_r > 0 and self._clear_laser_from_mill(p0, p1, max_r, a0, a1):
                self._laser_dirty = True
        return dirty

    def _clear_laser_from_mill(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        radius: float,
        a0: float,
        a1: float,
    ) -> bool:
        laser = self._laser
        if laser is None:
            return False
        if laser.mode == "cylindrical":
            return laser.clear_segment(
                p0[0],
                self._stock_theta(p0, a0),
                p1[0],
                self._stock_theta(p1, a1),
                radius,
            )
        return laser.clear_segment(p0[0], p0[1], p1[0], p1[1], radius)

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
        allow = self._laser_allow_mask(laser, p0, p1, a0, a1, radius)
        if laser.mode == "cylindrical":
            changed = laser.paint_segment(
                p0[0],
                self._stock_theta(p0, a0),
                p1[0],
                self._stock_theta(p1, a1),
                radius,
                allow,
                allow_origin=(0, 0),
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
                allow_origin=(0, 0),
                burn=burn,
            )
        if changed:
            self._laser_dirty = True
        elif self._laser is not None and not np.any(self._laser.intensity):
            self._drop_laser()
        return changed

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

    def _laser_allow_mask(
        self,
        laser: LaserMap,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        a0: float,
        a1: float,
        radius: float,
    ) -> np.ndarray:
        """True where a laser cell still has stock near the beam (skip air / pockets)."""
        z_mid = 0.5 * (p0[2] + p1[2])
        axis_y, axis_z = self._axis_yz()
        allow = np.zeros((laser.nx, laser.nv), dtype=bool)
        pad = radius + laser.cell_u
        iu0 = max(0, int(math.floor((min(p0[0], p1[0]) - pad - laser.origin_u) / laser.cell_u)))
        iu1 = min(laser.nx - 1, int(math.floor((max(p0[0], p1[0]) + pad - laser.origin_u) / laser.cell_u)))
        probe_r = min(
            0.5 * min(self.bounds.size[1], self.bounds.size[2]),
            math.hypot(p0[1] - axis_y, p0[2] - axis_z),
        )
        probe_r = max(0.0, probe_r - 0.51 * self.cell_size)
        if laser.wrap_v:
            pad_v = radius / max(laser.v_scale, 1e-12) + laser.cell_v
            iv_idx = laser._wrapped_v_indices(
                self._stock_theta(p0, a0),
                self._stock_theta(p1, a1),
                pad_v,
            )
            iv_range = iv_idx.tolist()
        else:
            iv0 = max(0, int(math.floor((min(p0[1], p1[1]) - pad - laser.origin_v) / laser.cell_v)))
            iv1 = min(laser.nv - 1, int(math.floor((max(p0[1], p1[1]) + pad - laser.origin_v) / laser.cell_v)))
            iv_range = range(iv0, iv1 + 1)
        for iu in range(iu0, iu1 + 1):
            x = laser.origin_u + (iu + 0.5) * laser.cell_u
            for iv in iv_range:
                iv = int(iv)
                if laser.wrap_v:
                    ang = math.radians((iv + 0.5) * laser.cell_v)
                    y = axis_y + math.sin(ang) * probe_r
                    z = axis_z + math.cos(ang) * probe_r
                    allow[iu, iv % laser.nv] = self.grid.is_solid_at_world(x, y, z)
                else:
                    y = laser.origin_v + (iv + 0.5) * laser.cell_v
                    allow[iu, iv] = self._stock_under_laser_xy(x, y, z_mid)
        return allow

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

    def mesh_tiles(self, keys: set[TileKey]) -> dict[TileKey, tuple | None]:
        return mesh_dirty_chunks(self.grid, keys)

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
