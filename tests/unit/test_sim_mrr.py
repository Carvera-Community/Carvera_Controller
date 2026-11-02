"""Per-vertex material removal rate recorded when a move is fully carved."""

from __future__ import annotations

import math
import time

import numpy as np
import pytest

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.heightmap import HeightmapBackend
from carveracontroller.addons.stock.simulator.native import HAS_NATIVE
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import RectangularStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType
from carveracontroller.CNC import LASER_TOOL_NUMBER
from carveracontroller.GcodeViewer import _segment_duration_sec

pytestmark = pytest.mark.skipif(not HAS_NATIVE, reason="native carve extension is not built")

_LIMITS = {"x": 3000.0, "y": 3000.0, "z": 2000.0, "a": 1800.0, "seek": 3000.0}
_SLOT_SEGMENTS = (
    ((5.0, 0.0, 12.0), (5.0, 0.0, 8.0), 0.0, 0.0),
    ((5.0, 0.0, 8.0), (25.0, 0.0, 8.0), 0.0, 0.0),
)


def _reference_slot_volumes():
    tool = _flat_tool()
    profile = resolve_cutting_profile(tool, tool_unit_scale=1.0)
    bounds = StockBounds(0, -10, 0, 40, 10, 10)
    reference = HeightmapBackend(bounds, 0.5, RectangularStock(40, 20, 10))
    volumes = np.zeros(2, dtype=np.float64)
    reference.carve_segments(list(_SLOT_SEGMENTS), profile, volumes=volumes)
    plunge_sec = _segment_duration_sec((5.0, 0.0, 12.0), (5.0, 0.0, 8.0), 0.0, 0.0, 300.0, _LIMITS)
    slot_sec = _segment_duration_sec((5.0, 0.0, 8.0), (25.0, 0.0, 8.0), 0.0, 0.0, 600.0, _LIMITS)
    return volumes, plunge_sec, slot_sec


def _wait_until(predicate, timeout=10.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _flat_tool() -> ToolDefinition:
    return ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=6.0,
        flute_length=10.0,
        length=40.0,
    )


def test_idle_bake_records_mrr_and_rewind_keeps_it():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(0, -10, 0, 40, 10, 10)
    cell = 0.5
    shape = RectangularStock(40, 20, 10)
    tool = _flat_tool()
    # Rapid down, plunge, slot, retract, then a laser stroke that removes no volume.
    positions = [
        5.0,
        0.0,
        12.0,
        5.0,
        0.0,
        8.0,
        25.0,
        0.0,
        8.0,
        25.0,
        0.0,
        12.0,
        35.0,
        0.0,
        8.0,
    ]
    vertex_types = [2.0, 1.0, 1.0, 2.0, 1.0]
    tools = [1, 1, 1, 1, LASER_TOOL_NUMBER]
    feeds = [0.0, 300.0, 600.0, 0.0, 100.0]

    volumes, plunge_sec, slot_sec = _reference_slot_volumes()
    expected_plunge = float(volumes[0]) * 60.0 / plunge_sec
    expected_slot = float(volumes[1]) * 60.0 / slot_sec

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=cell, enable=True, shape=shape, carver_mode="heightmap")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_mesh_updates_enabled(False)
        sim.set_idle_ahead_allowed(False)
        sim.set_toolpath(
            positions,
            vertex_types,
            tools,
            {1: tool},
            feeds=feeds,
            axis_limits=_LIMITS,
        )

        fresh = sim.mrr_values
        assert fresh is not None
        assert float(fresh[0]) == 0.0
        assert float(fresh[3]) == 0.0
        assert float(fresh[4]) == 0.0
        assert math.isnan(float(fresh[1]))
        assert math.isnan(float(fresh[2]))
        assert sim.mrr_at(0.0) == 0.0
        assert sim.mrr_at(1.2) is None

        sim.set_display_vertex(4)
        assert _wait_until(
            lambda: sim.mrr_values is not None and not np.isnan(sim.mrr_values).any(),
            timeout=5.0,
        )
        after_display = np.array(sim.mrr_values, copy=True)
        assert float(after_display[1]) == pytest.approx(expected_plunge, rel=1e-4, abs=1e-3)
        assert float(after_display[2]) == pytest.approx(expected_slot, rel=1e-4, abs=1e-3)

        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(
            lambda: sim.mrr_values is not None and not np.isnan(sim.mrr_values).any(),
            timeout=5.0,
        )
        baked = np.array(sim.mrr_values, copy=True)
        assert float(baked[0]) == 0.0
        assert float(baked[3]) == 0.0
        assert float(baked[4]) == 0.0
        assert baked[1] == pytest.approx(expected_plunge, rel=1e-4, abs=1e-3)
        assert baked[2] == pytest.approx(expected_slot, rel=1e-4, abs=1e-3)
        assert sim.mrr_at(0.2) == pytest.approx(float(baked[1]))
        assert sim.mrr_at(1.2) == pytest.approx(float(baked[2]))

        sim.set_display_vertex(0)
        assert _wait_until(lambda: sim.carved_vertex <= 0, timeout=5.0)
        sim.submit_idle_precompute(0)
        time.sleep(0.2)
        assert np.array_equal(sim.mrr_values, baked)

        sim.reset(bounds, cell_size_mm=cell, enable=True, shape=shape, carver_mode="heightmap")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        assert math.isnan(float(sim.mrr_values[1]))
        sim.set_mesh_updates_enabled(False)
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(
            lambda: sim.mrr_values is not None and not np.isnan(sim.mrr_values).any(),
            timeout=5.0,
        )
        assert np.allclose(sim.mrr_values, baked)

        sim.disable()
        assert sim.mrr_values is None
    finally:
        sim.stop()


def test_display_carve_to_end_records_mrr_without_idle_bake():
    """A file that opens with the playhead at the end never runs bake-ahead."""
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(0, -10, 0, 40, 10, 10)
    cell = 0.5
    shape = RectangularStock(40, 20, 10)
    tool = _flat_tool()
    positions = [5.0, 0.0, 12.0, 5.0, 0.0, 8.0, 25.0, 0.0, 8.0]
    feeds = [0.0, 300.0, 600.0]
    volumes, plunge_sec, slot_sec = _reference_slot_volumes()

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=cell, enable=True, shape=shape, carver_mode="heightmap")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_mesh_updates_enabled(False)
        sim.set_idle_ahead_allowed(False)
        sim.set_toolpath(
            positions,
            [1.0, 1.0, 1.0],
            [1, 1, 1],
            {1: tool},
            feeds=feeds,
            axis_limits=_LIMITS,
        )
        sim.set_display_vertex(2)
        assert _wait_until(
            lambda: sim.mrr_values is not None and not np.isnan(sim.mrr_values).any(),
            timeout=5.0,
        )
        assert sim._idle_ahead_allowed is False
        measured = sim.mrr_values
        assert float(measured[0]) == 0.0
        assert float(measured[1]) == pytest.approx(float(volumes[0]) * 60.0 / plunge_sec, rel=1e-4, abs=1e-3)
        assert float(measured[2]) == pytest.approx(float(volumes[1]) * 60.0 / slot_sec, rel=1e-4, abs=1e-3)
    finally:
        sim.stop()
