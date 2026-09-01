"""Initial solid occupancy for non-box stock shapes."""

from __future__ import annotations

import numpy as np

from carveracontroller.addons.stock.stock_geometry import contains_wcs
from carveracontroller.addons.stock.stock_shape import (
    CylindricalStock,
    RectangularStock,
    RotaryCylindricalStock,
    StockShape,
)

from .grid import CHUNK_FULL, ChunkCoord, ChunkedVoxelGrid

_NEIGHBOR_OFFSETS = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)


def seed_shape_occupancy(grid: ChunkedVoxelGrid, shape: StockShape | None) -> set[tuple[int, int, int]]:
    """Materialize non-box solids; leave rectangular stock as implicit FULL.

    Returns chunk keys that were written (EMPTY / array / collapsed FULL) so the
    initial mesh pass can dirty curved surfaces — not only the AABB shell.
    """
    if shape is None or isinstance(shape, RectangularStock):
        return set()
    if isinstance(shape, RotaryCylindricalStock):
        return _seed_x_cylinder(grid, shape)
    if isinstance(shape, CylindricalStock):
        return _seed_cylinder(grid, shape)
    # Unknown shapes: fall back to per-voxel contains_wcs over the AABB.
    return _seed_generic(grid, shape)


def _seed_cylinder(grid: ChunkedVoxelGrid, shape: CylindricalStock) -> set[tuple[int, int, int]]:
    bounds = grid.bounds
    cx, cy, _cz = bounds.center
    r = 0.5 * float(shape.diameter_mm)
    r2 = r * r
    dirty: set[tuple[int, int, int]] = set()
    for coord in _all_chunk_coords(grid):
        arr = grid.get_or_create_chunk(coord)
        if arr is None:
            continue
        solid = _cylinder_solid_mask(grid, coord, cx, cy, r2)
        arr[:] = 0
        arr[solid] = 1
        grid.maybe_collapse_chunk(coord, arr)
        dirty.add(coord.as_tuple())
    return dirty


def _seed_x_cylinder(grid: ChunkedVoxelGrid, shape: RotaryCylindricalStock) -> set[tuple[int, int, int]]:
    bounds = grid.bounds
    _cx, cy, cz = bounds.center
    r = 0.5 * float(shape.diameter_mm)
    r2 = r * r
    dirty: set[tuple[int, int, int]] = set()
    for coord in _all_chunk_coords(grid):
        arr = grid.get_or_create_chunk(coord)
        if arr is None:
            continue
        solid = _x_cylinder_solid_mask(grid, coord, cy, cz, r2)
        arr[:] = 0
        arr[solid] = 1
        grid.maybe_collapse_chunk(coord, arr)
        dirty.add(coord.as_tuple())
    return dirty


def _seed_generic(grid: ChunkedVoxelGrid, shape: StockShape) -> set[tuple[int, int, int]]:
    bounds = grid.bounds
    dirty: set[tuple[int, int, int]] = set()
    cs = grid.chunk_size
    for coord in _all_chunk_coords(grid):
        arr = grid.get_or_create_chunk(coord)
        if arr is None:
            continue
        valid = grid._valid_mask(coord)
        for lx in range(cs):
            for ly in range(cs):
                for lz in range(cs):
                    if not valid[lx, ly, lz]:
                        arr[lx, ly, lz] = 0
                        continue
                    ix = coord.cx * cs + lx
                    iy = coord.cy * cs + ly
                    iz = coord.cz * cs + lz
                    wx, wy, wz = grid.voxel_center(ix, iy, iz)
                    arr[lx, ly, lz] = 1 if contains_wcs(shape, bounds, wx, wy, wz) else 0
        grid.maybe_collapse_chunk(coord, arr)
        dirty.add(coord.as_tuple())
    return dirty


def _cylinder_solid_mask(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    cx: float,
    cy: float,
    r2: float,
) -> np.ndarray:
    """Boolean (cs,cs,cs) mask: in-bounds voxels whose XY center is inside the circle."""
    cs = grid.chunk_size
    valid = grid._valid_mask(coord)
    ix0 = coord.cx * cs
    iy0 = coord.cy * cs
    lx = np.arange(cs, dtype=np.float64)
    # Voxel-center world XY for each local index.
    wx = grid.bounds.min_x + (ix0 + lx + 0.5) * grid.voxel_size
    wy = grid.bounds.min_y + (iy0 + lx + 0.5) * grid.voxel_size
    # Broadcast to (cs, cs, 1) then rely on numpy broadcasting vs valid (cs,cs,cs).
    dx2 = (wx[:, None, None] - cx) ** 2
    dy2 = (wy[None, :, None] - cy) ** 2
    inside = (dx2 + dy2) <= r2
    return valid & inside


def _x_cylinder_solid_mask(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    cy: float,
    cz: float,
    r2: float,
) -> np.ndarray:
    """Boolean (cs,cs,cs) mask: in-bounds voxels whose YZ center is inside the circle."""
    cs = grid.chunk_size
    valid = grid._valid_mask(coord)
    iy0 = coord.cy * cs
    iz0 = coord.cz * cs
    lx = np.arange(cs, dtype=np.float64)
    wy = grid.bounds.min_y + (iy0 + lx + 0.5) * grid.voxel_size
    wz = grid.bounds.min_z + (iz0 + lx + 0.5) * grid.voxel_size
    dy2 = (wy[None, :, None] - cy) ** 2
    dz2 = (wz[None, None, :] - cz) ** 2
    inside = (dy2 + dz2) <= r2
    return valid & inside


def _all_chunk_coords(grid: ChunkedVoxelGrid):
    for cx in range(grid.n_chunks_x):
        for cy in range(grid.n_chunks_y):
            for cz in range(grid.n_chunks_z):
                yield ChunkCoord(cx, cy, cz)


def non_full_chunk_keys(grid: ChunkedVoxelGrid) -> set[tuple[int, int, int]]:
    """Keys stored in the grid that are not implicit/explicit FULL."""
    keys: set[tuple[int, int, int]] = set()
    for key, state in grid._chunks.items():
        if state is CHUNK_FULL:
            continue
        keys.add(key)
    return keys


def exterior_chunk_keys(grid: ChunkedVoxelGrid) -> set[tuple[int, int, int]]:
    """Chunk coords on the outer shell of the grid (have at least one stock face)."""
    keys: set[tuple[int, int, int]] = set()
    nx, ny, nz = grid.n_chunks_x, grid.n_chunks_y, grid.n_chunks_z
    for cx in range(nx):
        for cy in range(ny):
            for cz in range(nz):
                if cx in (0, nx - 1) or cy in (0, ny - 1) or cz in (0, nz - 1):
                    keys.add((cx, cy, cz))
    return keys


def expand_dirty_with_neighbors(
    grid: ChunkedVoxelGrid,
    dirty: set[tuple[int, int, int]],
) -> set[tuple[int, int, int]]:
    """Include 6-connected neighbours so pocket walls on FULL chunks are remeshed."""
    expanded = set(dirty)
    nx, ny, nz = grid.n_chunks_x, grid.n_chunks_y, grid.n_chunks_z
    for cx, cy, cz in dirty:
        for dx, dy, dz in _NEIGHBOR_OFFSETS:
            x, y, z = cx + dx, cy + dy, cz + dz
            if 0 <= x < nx and 0 <= y < ny and 0 <= z < nz:
                expanded.add((x, y, z))
    return expanded


# Test alias kept from the former simulator module.
_expand_dirty_with_neighbors = expand_dirty_with_neighbors
