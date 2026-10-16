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
    tile_keys_from_window_mask,
)
from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, TileKey
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LaserDecalMixin,
    LaserMap,
    laser_burn_uint8,
    pick_laser_cell_size_mm,
    split_laser_snapshot,
    stroke_parts,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.simulator.mesh_format import default_stock_color
from carveracontroller.addons.stock.stock_geometry import StockBounds, stock_theta_deg
from carveracontroller.addons.stock.stock_shape import (
    RectangularStock,
    RotaryCylindricalStock,
    StockShape,
)

_EMPTY_R = np.float32(-1.0)
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

    def _stock_theta(self, p: tuple[float, float, float], angle_deg: float) -> float:
        return stock_theta_deg(p[1], p[2], angle_deg, self.axis_y, self.axis_z)

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
        return self.engrave_segments([(p0, p1, a0, a1, power_s)])

    def engrave_segments(self, jobs, tool_unit_scale: float = 1.0) -> bool:
        del tool_unit_scale
        u0: list[float] = []
        v0: list[float] = []
        u1: list[float] = []
        v1: list[float] = []
        burns: list[int] = []
        min_r: list[float] = []
        for item in jobs:
            p0, p1, a0, a1, power = stroke_parts(item)
            burn = int(laser_burn_uint8(power))
            if not burn:
                continue
            d0 = math.hypot(float(p0[1]) - self.axis_y, float(p0[2]) - self.axis_z)
            d1 = math.hypot(float(p1[1]) - self.axis_y, float(p1[2]) - self.axis_z)
            u0.append(float(p0[0]))
            v0.append(self._stock_theta(p0, a0))
            u1.append(float(p1[0]))
            v1.append(self._stock_theta(p1, a1))
            burns.append(burn)
            min_r.append(min(d0, d1))
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
            wrap_v=laser.wrap_v,
            v_period=laser.v_period,
            v_scale=laser.v_scale,
            occ_kind=2,
            occ=self.radii,
            occ_min_x=float(self.bounds.min_x),
            occ_cell=float(self.cell_size),
            occ_d_theta=float(self.d_theta),
            occ_period=laser.v_period if laser.v_period else 360.0,
            z_or_r=min_r,
            dirty=laser.dirty_native_args(),
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
    ) -> set[TileKey]:
        del tool_unit_scale, tool_def
        if not segments or not profile:
            return set()
        if self.radii.shape != (self.nx, self.n_theta) or self._ox != 0:
            raise RuntimeError("cylindrical carve requires the full occupancy grid")
        from carveracontroller.addons.stock.simulator.native import carve_cylindrical

        laser = self._laser
        dirty, laser_changed = carve_cylindrical(
            self.radii,
            min_x=float(self.bounds.min_x),
            cell=float(self.cell_size),
            d_theta=float(self.d_theta),
            axis_y=float(self.axis_y),
            axis_z=float(self.axis_z),
            stock_radius=float(self.stock_radius),
            sin_t=self._sin_t,
            cos_t=self._cos_t,
            tile=int(self.tile_size),
            segments=list(segments),
            profile=profile,
            laser=None if laser is None else laser.intensity,
            laser_cell_u=0.0 if laser is None else laser.cell_u,
            laser_cell_v=0.0 if laser is None else laser.cell_v,
            laser_origin_u=0.0 if laser is None else laser.origin_u,
            laser_origin_v=0.0 if laser is None else laser.origin_v,
            laser_wrap=False if laser is None else laser.wrap_v,
            laser_period=360.0 if laser is None else laser.v_period,
            laser_dirty=None if laser is None else laser.dirty_native_args(),
        )
        if laser_changed:
            self._laser_dirty = True
        self._touched |= dirty
        return dirty

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

    def mesh_tiles(self, keys: set[TileKey], *, uniform: bool | None = None) -> dict[TileKey, tuple | None]:
        """Coalesced GPU meshes for the whole cylindrical shell (uint16-safe chunks)."""
        del uniform
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
    """Welded (x, θ) shell via the native extension (cut simulation requires it)."""
    from carveracontroller.addons.stock.simulator import native as native_mod

    if not backend.radii.size:
        return []
    return native_mod.mesh_cylinder_arrays(
        backend.radii,
        ix0=int(backend._ox),
        nx_total=int(backend.nx),
        min_x=float(backend.bounds.min_x),
        cell=float(backend.cell_size),
        axis_y=float(backend.axis_y),
        axis_z=float(backend.axis_z),
        sin_t=backend._sin_t,
        cos_t=backend._cos_t,
        floor_r=shell_floor_radius_mm(backend.cell_size),
        color=default_stock_color(),
    )
