"""Laser engraving decal map on stock carvers."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from carveracontroller.addons.stock.simulator.carvers.cylindrical import CylindricalBackend
from carveracontroller.addons.stock.simulator.carvers.heightmap import HeightmapBackend
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LASER_PREVIEW_GAMMA,
    LASER_SNAP_DELTA,
    LASER_SNAP_DROP,
    LASER_SNAP_FULL,
    LaserMap,
    apply_laser_tagged,
    laser_burn_uint8,
    laser_diff_payload,
    pick_laser_cell_size_mm,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.simulator.carvers.voxel import VoxelBackend
from carveracontroller.addons.stock.simulator.carvers.voxel.checkpoints import (
    CheckpointStore,
    restore_voxel_checkpoint,
)
from carveracontroller.addons.stock.simulator.worker import CarveJob, StockSimulator
from carveracontroller.addons.stock.stock_geometry import StockBounds, rotate_yz, stock_theta_deg
from carveracontroller.addons.stock.stock_shape import RectangularStock, RotaryCylindricalStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType
from carveracontroller.CNC import LASER_TOOL_NUMBER


def _flat_tool(diameter: float = 4.0) -> ToolDefinition:
    return ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=diameter,
        flute_length=10.0,
        length=40.0,
    )


def test_stroke_radius_clamped_to_beam():
    assert stroke_radius_mm(0.05) == 0.08
    assert stroke_radius_mm(1.0) == 0.12


def test_laser_cell_finer_than_occupancy():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    cell = pick_laser_cell_size_mm(bounds, 0.5)
    assert cell < 0.5
    assert cell <= 0.05


def _preview_burn(s: float) -> int:
    return int(round((s**LASER_PREVIEW_GAMMA) * 255.0))


def test_laser_burn_from_pwm_fraction():
    assert laser_burn_uint8(None) == 255
    assert laser_burn_uint8(0.0) == 0
    assert laser_burn_uint8(0.03) == _preview_burn(0.03)
    assert laser_burn_uint8(0.5) == _preview_burn(0.5)
    assert 0 < laser_burn_uint8(0.03) < laser_burn_uint8(0.5) < 255
    assert laser_burn_uint8(1.0) == 255
    assert laser_burn_uint8(100.0) == 255
    assert laser_burn_uint8(12000.0) == 0


def test_laser_map_paints_and_clears_capsule():
    bounds = StockBounds(0, 0, 0, 10, 10, 2)
    laser = LaserMap.planar(bounds, 20, 20, 0.5)
    assert laser.paint_segment(5.0, 5.0, 5.0, 5.0, 0.8, burn=255)
    assert laser.intensity_at(5.0, 5.0) == 255
    assert laser.clear_segment(5.0, 5.0, 5.0, 5.0, 0.8)
    assert laser.intensity_at(5.0, 5.0) == 0


def test_laser_map_clears_from_coarser_occupancy():
    bounds = StockBounds(0, 0, 0, 4, 4, 2)
    laser = LaserMap.planar(bounds, 8, 8, 0.5)
    assert laser.paint_segment(1.0, 1.0, 1.0, 1.0, 0.4, burn=255)
    assert laser.intensity_at(1.0, 1.0) == 255
    mask = np.zeros((2, 2), dtype=bool)
    mask[0, 0] = True
    assert laser.clear_from_coarse_mask(mask, 0, 0, 2.0, 2.0, 0.0, 0.0)
    assert laser.intensity_at(1.0, 1.0) == 0
    bounds = StockBounds(0, -10, -10, 20, 10, 10)
    laser = LaserMap.cylindrical(bounds, 10, 36, 2.0, 10.0)
    assert laser.paint_segment(10.0, 355.0, 10.0, 5.0, 2.0, burn=255)
    assert laser.intensity_at(10.0, 0.0) == 255
    assert laser.intensity_at(10.0, 180.0) == 0


def test_heightmap_mill_does_not_allocate_laser():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    assert hm._laser is None
    hm.carve_segment((-3.0, 0.0, 2.0), (3.0, 0.0, 2.0), _flat_tool(4.0))
    assert hm._laser is None
    assert hm.laser_gpu_payload() is None


def test_heightmap_engrave_then_mill_clears():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    assert hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    assert hm._laser is not None
    assert hm._laser.intensity_at(0.0, 0.0) == 255
    hm.carve_segment((-3.0, 0.0, 2.0), (3.0, 0.0, 2.0), _flat_tool(4.0))
    assert hm._laser.intensity_at(0.0, 0.0) == 0


def test_heightmap_pwm_scales_and_keeps_max():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    assert not hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0), power_s=0.0)
    assert hm._laser is None
    assert hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0), power_s=0.03)
    assert hm._laser is not None
    assert hm._laser.intensity_at(0.0, 0.0) == _preview_burn(0.03)
    hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0), power_s=1.0)
    assert hm._laser.intensity_at(0.0, 0.0) == 255
    hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0), power_s=0.1)
    assert hm._laser.intensity_at(0.0, 0.0) == 255


def test_heightmap_laser_finer_than_occupancy():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    assert hm._laser is not None
    assert hm._laser.cell_u < hm.cell_size
    assert hm._laser.nx > hm.nx


def test_heightmap_skip_air_over_pocket():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.carve_segment((-3.0, 0.0, 0.5), (3.0, 0.0, 0.5), _flat_tool(6.0))
    pocket_z = hm.height_at_world(0.0, 0.0)
    assert pocket_z is not None and pocket_z < 2.0
    # Laser at original top over the pocket should not paint the floor.
    hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    if hm._laser is not None:
        assert hm._laser.intensity_at(0.0, 0.0) == 0


def test_laser_sparse_delta_roundtrip():
    prev = np.zeros((16, 16), dtype=np.uint8)
    curr = prev.copy()
    curr[3, 4] = 200
    curr[7, 1] = 40
    payload = laser_diff_payload(prev, curr)
    assert payload is not None
    assert payload[0] == LASER_SNAP_DELTA
    laser = LaserMap.planar(StockBounds(0, 0, 0, 8, 8, 1), 16, 16, 0.5)
    apply_laser_tagged(laser, payload)
    assert laser.intensity[3, 4] == 200
    assert laser.intensity[7, 1] == 40
    assert int(laser.intensity.sum()) == 240


def test_laser_oversized_delta_falls_back_to_full():
    prev = np.zeros((20, 20), dtype=np.uint8)
    curr = np.full((20, 20), 255, dtype=np.uint8)
    payload = laser_diff_payload(prev, curr)
    assert payload is not None
    assert payload[0] == LASER_SNAP_FULL


def test_heightmap_laser_checkpoint_roundtrip():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.engrave_segment((0.0, 0.0, 5.0), (2.0, 0.0, 5.0))
    payload = hm.snapshot_full()
    assert len(payload) == 3
    assert payload[2][0] == LASER_SNAP_FULL
    hm2 = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm2.restore(payload)
    assert hm2._laser is not None
    assert hm2._laser.intensity_at(0.0, 0.0) == hm._laser.intensity_at(0.0, 0.0)
    empty = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5)).snapshot_full()
    hm2.restore(empty)
    assert hm2._laser is None


def test_heightmap_laser_gop_omit_does_not_drop():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    mill_base = hm.snapshot_full()
    assert len(mill_base) == 2
    assert hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    first = hm.snapshot_changed(set())
    assert first[0] == "delta"
    assert first[2][0] == LASER_SNAP_FULL
    mill_delta = hm.snapshot_changed(set())
    assert len(mill_delta) == 2
    assert hm.engrave_segment((2.0, 0.0, 5.0), (2.0, 0.0, 5.0))
    sparse = hm.snapshot_changed(set())
    assert sparse[2][0] == LASER_SNAP_DELTA
    burn0 = hm._laser.intensity_at(0.0, 0.0)
    burn2 = hm._laser.intensity_at(2.0, 0.0)

    hm2 = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm2.restore(mill_base)
    hm2.restore(first)
    assert hm2._laser is not None
    assert hm2._laser.intensity_at(0.0, 0.0) == burn0
    hm2.restore(mill_delta)
    assert hm2._laser is not None
    assert hm2._laser.intensity_at(0.0, 0.0) == burn0
    hm2.restore(sparse)
    assert hm2._laser.intensity_at(0.0, 0.0) == burn0
    assert hm2._laser.intensity_at(2.0, 0.0) == burn2


def test_heightmap_laser_drop_delta():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    assert hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    full = hm.snapshot_full()
    hm._drop_laser()
    dropped = hm.snapshot_changed(set())
    assert dropped[2] == (LASER_SNAP_DROP,)
    hm2 = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm2.restore(full)
    assert hm2._laser is not None
    hm2.take_laser_dirty()
    hm2.restore(dropped)
    assert hm2._laser is None
    assert hm2.take_laser_dirty() is True
    assert hm2.laser_gpu_payload() is None


def test_reset_occupancy_marks_laser_dirty_for_gpu_drop():
    """Seek before the first checkpoint resets occupancy with no laser extra."""
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.reset_occupancy()
    assert hm.take_laser_dirty() is False

    assert hm.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    assert hm.take_laser_dirty() is True
    hm.reset_occupancy()
    assert hm._laser is None
    assert hm.laser_gpu_payload() is None
    assert hm.take_laser_dirty() is True

    vx_bounds = StockBounds(-10, -10, -5, 10, 10, 5)
    vx = VoxelBackend(vx_bounds, 1.0, RectangularStock(20, 20, 10), laser_cell_size_mm=0.05)
    assert vx.engrave_segment((0.0, 0.0, 4.0), (0.0, 0.0, 4.0))
    vx.take_laser_dirty()
    vx.reset_occupancy()
    assert vx._laser is None
    assert vx.take_laser_dirty() is True


def test_voxel_laser_checkpoint_gop_restore():
    bounds = StockBounds(-10, -10, -5, 10, 10, 5)
    shape = RectangularStock(20, 20, 10)
    vx = VoxelBackend(bounds, 1.0, shape, laser_cell_size_mm=0.05)
    store = CheckpointStore(slot_count=4, base_interval=4)
    store.set_path_vertex_count(20)
    assert vx.engrave_segment((0.0, 0.0, 4.0), (0.0, 0.0, 4.0))
    assert store.maybe_record(5, vx, None)
    assert store._items[-1].is_base
    assert store._items[-1].laser[0] == LASER_SNAP_FULL
    assert vx.engrave_segment((2.0, 0.0, 4.0), (2.0, 0.0, 4.0))
    assert store.maybe_record(10, vx, set())
    assert store._items[-1].laser[0] == LASER_SNAP_DELTA
    burn0 = vx._laser.intensity_at(0.0, 0.0)
    burn2 = vx._laser.intensity_at(2.0, 0.0)

    vx2 = VoxelBackend(bounds, 1.0, shape, laser_cell_size_mm=0.05)
    restore_voxel_checkpoint(vx2, store, store._items[-1])
    assert vx2._laser is not None
    assert vx2._laser.intensity_at(0.0, 0.0) == burn0
    assert vx2._laser.intensity_at(2.0, 0.0) == burn2


def test_cylindrical_engrave_wraps_and_mill_clears():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    cyl = CylindricalBackend(bounds, 1.0, RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0))
    assert cyl._laser is None
    cyl.carve_segment((8.0, 0.0, 8.0), (8.0, 0.0, 8.0), _flat_tool(6.0), a0=90.0, a1=90.0)
    assert cyl._laser is None
    assert cyl.engrave_segment((20.0, 0.0, 14.0), (20.0, 0.0, 14.0), a0=0.0, a1=0.0)
    assert cyl._laser is not None
    assert cyl._laser.intensity_at(20.0, 0.0) == 255
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), _flat_tool(6.0), a0=0.0, a1=0.0)
    assert cyl._laser.intensity_at(20.0, 0.0) == 0


def test_cylindrical_engrave_uses_stock_theta_not_a():
    """A=90 with the tool on +Z must mark stock θ=-90 (mill's A90 side), not +90."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    cyl = CylindricalBackend(bounds, 1.0, RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0))
    tip = (20.0, 0.0, 14.0)
    assert cyl.engrave_segment(tip, tip, a0=90.0, a1=90.0)
    theta = stock_theta_deg(tip[1], tip[2], 90.0, cyl.axis_y, cyl.axis_z)
    assert theta == pytest.approx(-90.0)
    assert cyl._laser is not None
    assert cyl._laser.intensity_at(20.0, theta) == 255
    assert cyl._laser.intensity_at(20.0, 90.0) == 0
    assert cyl._laser.intensity_at(20.0, 0.0) == 0
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), _flat_tool(6.0), a0=90.0, a1=90.0)
    assert cyl._laser.intensity_at(20.0, theta) == 0
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(20.0, y, z)


def test_voxel_engrave_and_mill_clear():
    bounds = StockBounds(-10, -10, -5, 10, 10, 5)
    vx = VoxelBackend(bounds, 1.0, RectangularStock(20, 20, 10), laser_cell_size_mm=0.05)
    assert vx._laser is None
    vx.carve_segment((-8.0, 8.0, 4.0), (-6.0, 8.0, 4.0), _flat_tool(4.0))
    assert vx._laser is None
    assert vx.engrave_segment((0.0, 0.0, 4.0), (0.0, 0.0, 4.0))
    assert vx._laser is not None
    assert vx._laser.intensity_at(0.0, 0.0) == 255
    vx.carve_segment((-3.0, 0.0, 0.0), (3.0, 0.0, 0.0), _flat_tool(6.0))
    assert vx._laser.intensity_at(0.0, 0.0) == 0


def test_voxel_engrave_at_stock_top_plane():
    """Laser at Z = stock max_z must still mark remaining stock (AABB is exclusive)."""
    bounds = StockBounds(-10, -10, -5, 10, 10, 5)
    vx = VoxelBackend(bounds, 1.0, RectangularStock(20, 20, 10), laser_cell_size_mm=0.05)
    assert vx.engrave_segment((0.0, 0.0, 5.0), (0.0, 0.0, 5.0))
    assert vx._laser is not None
    assert vx._laser.intensity_at(0.0, 0.0) == 255


def test_voxel_rotary_engrave_uses_stock_theta_not_a():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    vx = VoxelBackend(
        bounds,
        1.0,
        RectangularStock(40, 28, 28),
        has_4axis=True,
        laser_cell_size_mm=0.05,
    )
    tip = (20.0, 0.0, 14.0)
    assert vx.engrave_segment(tip, tip, a0=90.0, a1=90.0)
    theta = vx._stock_theta(tip, 90.0)
    assert theta == pytest.approx(-90.0)
    assert vx._laser is not None
    assert vx._laser.intensity_at(20.0, theta) == 255
    assert vx._laser.intensity_at(20.0, 90.0) == 0
    vx.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), _flat_tool(6.0), a0=90.0, a1=90.0)
    assert vx._laser.intensity_at(20.0, theta) == 0


def test_worker_laser_does_not_carve_occupancy():
    sim = StockSimulator()
    backend = MagicMock()
    backend.engrave_segment.return_value = True
    job = CarveJob(
        p0=(0.0, 0.0, 0.0),
        p1=(1.0, 0.0, 0.0),
        tool_def=None,
        is_cut=True,
        tool_number=LASER_TOOL_NUMBER,
    )
    dirty = sim._carve_one(backend, job)
    assert dirty == set()
    backend.engrave_segment.assert_called_once()
    backend.carve_segment.assert_not_called()
    mill = CarveJob(
        p0=(0.0, 0.0, 0.0),
        p1=(1.0, 0.0, 0.0),
        tool_def=_flat_tool(),
        is_cut=True,
        tool_number=1,
    )
    backend.carve_segment.return_value = {(0, 0, 0)}
    assert sim._carve_one(backend, mill) == {(0, 0, 0)}
    backend.carve_segment.assert_called_once()


def test_worker_skips_laser_z_plunge():
    sim = StockSimulator()
    backend = MagicMock()
    job = CarveJob(
        p0=(0.0, 0.0, 5.0),
        p1=(0.0, 0.0, 0.0),
        tool_def=None,
        is_cut=True,
        tool_number=LASER_TOOL_NUMBER,
    )
    assert sim._carve_one(backend, job) == set()
    backend.engrave_segment.assert_not_called()
    backend.carve_segment.assert_not_called()
