"""Unit tests for non-box stock voxel occupancy seeding."""

from carveracontroller.addons.stock.simulator.carvers.voxel.grid import ChunkedVoxelGrid
from carveracontroller.addons.stock.simulator.carvers.voxel.occupancy import non_full_chunk_keys, seed_shape_occupancy
from carveracontroller.addons.stock.stock_geometry import compute_wcs_bounds
from carveracontroller.addons.stock.stock_origin import (
    CORNER_BL,
    CORNER_CENTER,
    CORNER_LC,
    Z_BOTTOM,
    Z_CENTER,
    Z_TOP,
    StockOrigin,
)
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RectangularStock, RotaryCylindricalStock


def test_rectangular_seed_is_noop():
    shape = RectangularStock(40, 40, 10)
    bounds = compute_wcs_bounds(shape, StockOrigin(xy_corner=CORNER_BL, z_reference=Z_TOP))
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=2.0, chunk_size=8)
    dirty = seed_shape_occupancy(grid, shape)
    assert dirty == set()
    assert grid._chunks == {}
    assert grid.is_solid_at_world(1.0, 1.0, -1.0)
    assert grid.is_solid_at_world(39.0, 39.0, -1.0)


def test_cylinder_seed_axis_solid_corner_empty():
    shape = CylindricalStock(diameter_mm=40, height_mm=10)
    bounds = compute_wcs_bounds(shape, StockOrigin(xy_corner=CORNER_CENTER, z_reference=Z_TOP))
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    dirty = seed_shape_occupancy(grid, shape)
    assert dirty
    # Axis near mid-height
    assert grid.is_solid_at_world(0.0, 0.0, -5.0)
    # AABB corner outside the circle
    assert not grid.is_solid_at_world(-19.5, -19.5, -5.0)
    assert not grid.is_solid_at_world(19.5, 19.5, -5.0)
    # Outside Z extent
    assert not grid.is_solid_at_world(0.0, 0.0, 1.0)


def test_cylinder_seed_respects_z_bottom():
    shape = CylindricalStock(diameter_mm=20, height_mm=8)
    bounds = compute_wcs_bounds(shape, StockOrigin(xy_corner=CORNER_BL, z_reference=Z_BOTTOM))
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    seed_shape_occupancy(grid, shape)
    assert grid.is_solid_at_world(10.0, 10.0, 4.0)
    assert not grid.is_solid_at_world(10.0, 10.0, -0.5)
    assert not grid.is_solid_at_world(0.5, 0.5, 4.0)


def test_cylinder_seed_materializes_non_full_chunks():
    shape = CylindricalStock(diameter_mm=32, height_mm=8)
    bounds = compute_wcs_bounds(shape, StockOrigin(xy_corner=CORNER_CENTER, z_reference=Z_TOP))
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=2.0, chunk_size=4)
    seed_shape_occupancy(grid, shape)
    # AABB corners empty; axis solid.
    assert not grid.is_solid_at_world(-15.0, -15.0, -4.0)
    assert grid.is_solid_at_world(0.0, 0.0, -4.0)
    # Seeding must leave explicit non-FULL chunks (EMPTY and/or arrays).
    assert non_full_chunk_keys(grid)


def test_rotary_cylinder_seed_axis_solid_corner_empty():
    shape = RotaryCylindricalStock(diameter_mm=40, length_mm=80)
    bounds = compute_wcs_bounds(shape, StockOrigin(xy_corner=CORNER_LC, z_reference=Z_CENTER))
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    dirty = seed_shape_occupancy(grid, shape)
    assert dirty
    assert grid.is_solid_at_world(40.0, 0.0, 0.0)
    assert grid.is_solid_at_world(40.0, 0.0, 19.0)
    assert not grid.is_solid_at_world(40.0, 19.0, 19.0)
