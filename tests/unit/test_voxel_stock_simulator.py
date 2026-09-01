"""Unit tests for voxel stock cut simulation."""

import time

import numpy as np
import pytest

from carveracontroller.addons.stock.simulator import carve_segment_into_grid
from carveracontroller.addons.stock.simulator.carvers.voxel.grid import ChunkedVoxelGrid
from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import mesh_chunk
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType


def _wait_until(predicate, timeout=10.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _flat_tool(number=1, diameter=2.0, flute_length=4.0, length=10.0):
    return ToolDefinition(
        number=number,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=diameter,
        flute_length=flute_length,
        length=length,
    )


def _linear_x_toolpath(n_steps, x0, dx, z=-1.0, tool_number=1):
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for i in range(n_steps + 1):
        positions.extend((x0 + i * dx, 0.0, z))
        vertex_types.append(1.0)
        tools.append(tool_number)
    vertex_types[0] = 2.0
    return positions, vertex_types, tools


def _assert_snapshots_equal(actual, expected):
    assert set(actual.keys()) == set(expected.keys())
    for key in expected:
        exp = expected[key]
        got = actual[key]
        if hasattr(exp, "shape"):
            assert np.array_equal(got, exp)
        else:
            assert got is exp


def _small_grid(voxel=1.0):
    # Stock from (-5,-5,-5) to (5,5,0) — top at Z0, 10×10×5 mm
    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)
    return ChunkedVoxelGrid(bounds, voxel_size_mm=voxel, chunk_size=8)


def test_untouched_stock_is_solid():
    grid = _small_grid()
    assert grid.is_solid_at_world(0.0, 0.0, -1.0)
    assert grid.is_solid_at_world(0.0, 0.0, -4.5)


def test_flat_end_mill_clears_slot():
    grid = _small_grid(voxel=0.5)
    tool = _flat_tool()
    carve_segment_into_grid(grid, (-3.0, 0.0, -1.0), (3.0, 0.0, -1.0), tool)

    assert not grid.is_solid_at_world(0.0, 0.0, -0.75)
    assert grid.is_solid_at_world(0.0, 4.0, -1.0)
    # Flat mill clears above the tip; deep below stays solid.
    assert not grid.is_solid_at_world(0.0, 0.0, -0.25)
    assert grid.is_solid_at_world(0.0, 0.0, -4.5)


def test_ball_nose_leaves_rounded_bottom_relative_to_flat():
    """Ball nose clears less material at the tip edge than a flat mill of same Ø."""
    tool_flat = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=4.0,
        flute_length=6.0,
        length=12.0,
    )
    tool_ball = ToolDefinition(
        number=2,
        tool_type=ToolType.BALL_END_MILL,
        diameter=4.0,
        flute_length=6.0,
        length=12.0,
    )

    grid_flat = _small_grid(voxel=0.5)
    grid_ball = _small_grid(voxel=0.5)
    carve_segment_into_grid(grid_flat, (0.0, 0.0, -1.0), (0.0, 0.0, -1.0), tool_flat)
    carve_segment_into_grid(grid_ball, (0.0, 0.0, -1.0), (0.0, 0.0, -1.0), tool_ball)

    # At the tip plane near the outer radius, a flat mill clears a full cylinder
    # while a ball nose has near-zero radius at the south pole and grows with height.
    # Sample a point slightly above the tip and near the cutting radius.
    sample = (1.7, 0.0, -0.6)  # z_rel ≈ 0.4; ball radius there < flat's 2.0
    flat_cleared = not grid_flat.is_solid_at_world(*sample)
    ball_cleared = not grid_ball.is_solid_at_world(*sample)
    assert flat_cleared
    assert not ball_cleared


def _ramp_grid(voxel=0.5):
    # Large enough for a (0,0,0)→(10,0,-5) ramp with flute clearance above the tip path.
    bounds = StockBounds(min_x=-1, min_y=-5, min_z=-8, max_x=12, max_y=5, max_z=2)
    return ChunkedVoxelGrid(bounds, voxel_size_mm=voxel, chunk_size=8)


def test_ramp_flat_mill_clears_on_path_above_tip():
    """Simultaneous XY+Z motion must clear voxels above a later (lower) tip pose."""
    grid = _ramp_grid(voxel=0.5)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=6.0,
        length=12.0,
    )
    carve_segment_into_grid(grid, (0.0, 0.0, 0.0), (10.0, 0.0, -5.0), tool)

    # Near the end of the ramp, on-axis, above the tip path (tip≈-4.5 at x=9).
    # 3D-closest tip wrongly leaves this solid; Z-window + XY-closest clears it.
    assert not grid.is_solid_at_world(9.0, 0.0, -1.0)
    # Far off-axis at the same height stays solid.
    assert grid.is_solid_at_world(9.0, 3.0, -1.0)
    # Below the entire tip path → empty Z-window → solid.
    assert grid.is_solid_at_world(5.0, 0.0, -7.5)


def test_helical_ish_move_clears_on_path():
    """XY+Z diagonal (helix-ish) clears an on-path voxel above the tip path."""
    grid = _ramp_grid(voxel=0.5)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=6.0,
        length=12.0,
    )
    carve_segment_into_grid(grid, (0.0, 0.0, 0.0), (8.0, 4.0, -4.0), tool)

    # Mid-late on the XY path, above the tip at that station.
    assert not grid.is_solid_at_world(6.0, 3.0, -0.5)


def test_mesh_chunk_produces_geometry_after_carve():
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import ChunkCoord

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=3.0,
        flute_length=5.0,
        length=10.0,
    )
    dirty = carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    assert dirty
    # Mesh at least one dirty chunk that still has solid material.
    meshed = False
    for key in dirty:
        coord = ChunkCoord(*key)
        state = grid.get_chunk_state(coord)
        if hasattr(state, "any") and state.any():
            packed = mesh_chunk(grid, coord, state)
            if packed is not None:
                verts, indices, fmt = packed
                assert len(verts) > 0
                assert len(indices) >= 6
                meshed = True
                break
    assert meshed


def test_greedy_rects_cover_mask_exactly():
    from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import _greedy_rects

    rng = np.random.default_rng(0)
    mask = rng.random((16, 16)) > 0.55
    i0, j0, i1, j1 = _greedy_rects(mask)
    covered = np.zeros_like(mask)
    for a, b, c, d in zip(i0, j0, i1, j1):
        assert not covered[a:c, b:d].any()
        covered[a:c, b:d] = True
    assert np.array_equal(covered, mask)
    full_i0, full_j0, full_i1, full_j1 = _greedy_rects(np.ones((8, 8), dtype=bool))
    assert list(full_i0) == [0] and list(full_j0) == [0]
    assert list(full_i1) == [8] and list(full_j1) == [8]


def test_full_cube_greedy_mesh_is_six_quads():
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import ChunkCoord
    from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import mesh_chunk_state

    bounds = StockBounds(min_x=0, min_y=0, min_z=0, max_x=8, max_y=8, max_z=8)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    packed = mesh_chunk_state(grid, ChunkCoord(0, 0, 0))
    assert packed is not None
    verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
    # 6 faces × 4 verts; greedy merge turns each face into one quad.
    assert verts.shape[0] == 24
    pos = verts[:, :3]
    assert pos[:, 0].min() == pytest.approx(0.0)
    assert pos[:, 0].max() == pytest.approx(8.0)
    assert pos[:, 1].min() == pytest.approx(0.0)
    assert pos[:, 1].max() == pytest.approx(8.0)
    assert pos[:, 2].min() == pytest.approx(0.0)
    assert pos[:, 2].max() == pytest.approx(8.0)
    indices = packed[1]
    assert len(indices) == 36  # 6 quads × 2 tris × 3


def test_indexed_a90_does_not_allocate_far_chunks():
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_FULL, ChunkCoord

    bounds = StockBounds(min_x=0, min_y=-40, min_z=-40, max_x=80, max_y=40, max_z=40)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    carve_segment_into_grid(grid, (40.0, 0.0, 8.0), (40.0, 0.0, 8.0), tool, a0=90.0, a1=90.0)
    far = ChunkCoord(cx=grid.n_chunks_x - 1, cy=0, cz=0)
    assert grid.get_chunk_state(far) is CHUNK_FULL or far.as_tuple() not in grid._chunks
    assert not isinstance(grid.get_chunk_state(far), np.ndarray)


def test_full_chunk_and_neighbors_mesh_pocket_floor():
    """FULL shell chunks must mesh; carved neighbors expose pocket floors."""
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_FULL, ChunkCoord
    from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import mesh_chunk_state, mesh_dirty_chunks

    grid = _small_grid(voxel=1.0)
    # Exterior FULL chunk (top) should produce a surface even before any carve.
    top = ChunkCoord(0, 0, grid.n_chunks_z - 1)
    assert grid.get_chunk_state(top) is CHUNK_FULL
    packed = mesh_chunk_state(grid, top)
    assert packed is not None
    assert len(packed[0]) > 0

    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=4.0,
        flute_length=5.0,
        length=10.0,
    )
    dirty = carve_segment_into_grid(grid, (0.0, 0.0, -1.0), (0.0, 0.0, -1.0), tool)
    meshes = mesh_dirty_chunks(grid, dirty)
    # At least one chunk near the carve should still have drawable faces (floor/walls).
    assert any(v is not None for v in meshes.values())


def test_snapshot_non_full_omits_full_and_restores():
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_EMPTY, CHUNK_FULL

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=3.0,
        flute_length=5.0,
        length=10.0,
    )
    carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    assert not grid.is_solid_at_world(0.0, 0.0, -0.5)

    snap, nbytes = grid.snapshot_non_full()
    assert nbytes > 0
    assert all(state is not CHUNK_FULL for state in snap.values())
    assert any(state is CHUNK_EMPTY or hasattr(state, "shape") for state in snap.values())

    grid.reset()
    assert grid.is_solid_at_world(0.0, 0.0, -0.5)
    grid.restore_non_full(snap)
    assert not grid.is_solid_at_world(0.0, 0.0, -0.5)
    assert grid.is_solid_at_world(0.0, 4.0, -1.0)


def test_checkpoint_store_equal_spaced_targets():
    from carveracontroller.addons.stock.simulator import CheckpointStore

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    # 101 vertices → last=100; 4 slots → targets 25, 50, 75, 100.
    store = CheckpointStore(slot_count=4)
    store.set_path_vertex_count(101)
    assert store.target_count == 4
    assert store._targets == [25, 50, 75, 100]

    carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (0.0, 0.0, -1.0), tool)
    assert not store.maybe_record(10, grid)  # before first target
    assert store.maybe_record(25, grid)
    assert not store.maybe_record(40, grid)  # between targets
    carve_segment_into_grid(grid, (0.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    assert store.maybe_record(50, grid)

    best = store.best_at_or_before(40)
    assert best is not None and best.vertex == 25
    best = store.best_at_or_before(200)
    assert best is not None and best.vertex == 50
    assert store.best_at_or_before(10) is None


def test_checkpoint_short_path_dedupes_targets():
    from carveracontroller.addons.stock.simulator import CheckpointStore

    store = CheckpointStore(slot_count=256)
    store.set_path_vertex_count(5)  # last=4 → many rounds collapse
    assert store.target_count < 256
    assert store.target_count >= 1
    assert store._targets[-1] == 4
    assert all(t > 0 for t in store._targets)


def test_set_path_vertex_count_same_length_preserves_checkpoints():
    """Seek/recarve republishes the toolpath; identical V must not wipe slots."""
    from carveracontroller.addons.stock.simulator import CheckpointStore

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    store = CheckpointStore(slot_count=4)
    store.set_path_vertex_count(101)
    carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    assert store.maybe_record(25, grid)
    assert store.maybe_record(50, grid)
    assert len(store) == 2

    store.set_path_vertex_count(101)  # same length — e.g. _recarve_stock_to republish
    assert len(store) == 2
    assert store.vertices() == [25, 50]

    store.set_path_vertex_count(201)  # real path change
    assert len(store) == 0
    assert store.target_count > 0


def test_checkpoint_bit_packing_shrinks_payload():
    from carveracontroller.addons.stock.simulator import (
        CheckpointStore,
        _pack_chunk_state,
        _unpack_chunk_state,
    )

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=3.0,
        flute_length=5.0,
        length=10.0,
    )
    carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    raw, raw_nbytes = grid.snapshot_non_full()
    assert raw_nbytes > 0

    store = CheckpointStore(slot_count=8)
    store.set_path_vertex_count(20)
    assert store.maybe_record(store._targets[0], grid, changed_keys=None)
    cp = store.best_at_or_before(store._targets[0])
    assert cp is not None and cp.is_base

    # Packed payload must be ~8x smaller than the raw uint8-per-voxel form.
    assert 0 < cp.nbytes < raw_nbytes

    for key, state in raw.items():
        packed = _pack_chunk_state(state)
        cs = grid.chunk_size
        restored = _unpack_chunk_state(packed, cs)
        if hasattr(state, "shape"):
            assert np.array_equal(restored, state)
        else:
            assert restored is state  # CHUNK_EMPTY sentinel round-trips


def test_delta_checkpoints_form_gops_and_reconstruct():
    from carveracontroller.addons.stock.simulator import CheckpointStore

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    store = CheckpointStore(slot_count=4, base_interval=3)
    # Targets at 10,20,30,40 for V=41.
    store.set_path_vertex_count(41)
    assert store._targets == [10, 20, 30, 40]

    # Carve incrementally, tracking which chunks changed each step (mirrors
    # what the worker loop accumulates from carve_segment_into_grid's return).
    steps = [
        ((-4.0, 0.0, -1.0), (-2.0, 0.0, -1.0)),
        ((-2.0, 0.0, -1.0), (0.0, 0.0, -1.0)),
        ((0.0, 0.0, -1.0), (2.0, 0.0, -1.0)),
        ((2.0, 0.0, -1.0), (4.0, 0.0, -1.0)),
    ]
    recorded_vertices = []
    for i, (p0, p1) in enumerate(steps, start=1):
        dirty = carve_segment_into_grid(grid, p0, p1, tool)
        assert store.maybe_record(i * 10, grid, changed_keys=dirty)
        recorded_vertices.append(i * 10)

    # First checkpoint of every GOP must be a base; base_interval=3 → indices 0,3.
    assert store._items[0].is_base
    assert not store._items[1].is_base
    assert not store._items[2].is_base
    assert store._items[3].is_base

    # Every checkpoint must reconstruct to match a freshly-carved grid up to
    # that point (bit-for-bit, regardless of base/delta encoding).
    for i, vertex in enumerate(recorded_vertices):
        cp = store.best_at_or_before(vertex)
        assert cp is not None and cp.vertex == vertex
        reconstructed = store.resolve_chunks(cp, grid.chunk_size)

        reference_grid = _small_grid(voxel=1.0)
        for p0, p1 in steps[: i + 1]:
            carve_segment_into_grid(reference_grid, p0, p1, tool)
        expected, _ = reference_grid.snapshot_non_full()

        assert set(reconstructed.keys()) == set(expected.keys())
        for key in expected:
            exp = expected[key]
            got = reconstructed[key]
            if hasattr(exp, "shape"):
                assert np.array_equal(got, exp)
            else:
                assert got is exp


def test_empty_delta_pframe_is_recorded_and_resolves_to_prior_base():
    """Blank stretches must still place seek anchors (empty P-frames)."""
    from carveracontroller.addons.stock.simulator import CheckpointStore

    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    store = CheckpointStore(slot_count=4, base_interval=4)
    store.set_path_vertex_count(101)  # targets 25, 50, 75, 100
    assert store._targets == [25, 50, 75, 100]

    carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    assert store.maybe_record(25, grid, changed_keys=None)
    base = store._items[0]
    assert base.is_base
    base_resolved = store.resolve_chunks(base, grid.chunk_size)

    # No further carving — empty changed set at the next target.
    assert store.maybe_record(50, grid, changed_keys=set())
    assert len(store) == 2
    empty_cp = store._items[1]
    assert not empty_cp.is_base
    assert empty_cp.data == {}
    assert empty_cp.nbytes == 0
    assert empty_cp.vertex == 50

    best = store.best_at_or_before(40)
    assert best is not None and best.vertex == 25
    best = store.best_at_or_before(50)
    assert best is not None and best is empty_cp

    resolved = store.resolve_chunks(empty_cp, grid.chunk_size)
    assert set(resolved.keys()) == set(base_resolved.keys())
    for key in base_resolved:
        exp = base_resolved[key]
        got = resolved[key]
        if hasattr(exp, "shape"):
            assert np.array_equal(got, exp)
        else:
            assert got is exp


def test_idle_precompute_carves_to_end_of_file():
    """Idle precompute carves the toolpath tail and records checkpoints."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 200
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-10.0, dx=0.1)

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(lambda: sim.bake_grid is not None and not sim.bake_grid.is_solid_at_world(9.0, 0.0, -0.5))

        with sim._lock:
            assert len(sim._checkpoints) > 0
            assert sim._grid_carved_vertex == 0

        reference_grid = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5)
        for i in range(1, n_steps + 1):
            p0 = (positions[(i - 1) * 3], positions[(i - 1) * 3 + 1], positions[(i - 1) * 3 + 2])
            p1 = (positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
            carve_segment_into_grid(reference_grid, p0, p1, tool)
        expected, _ = reference_grid.snapshot_non_full()
        actual, _ = sim.bake_grid.snapshot_non_full()
        _assert_snapshots_equal(actual, expected)
        assert sim.grid.is_solid_at_world(9.0, 0.0, -0.5)
    finally:
        sim.stop()


def test_idle_bake_fills_last_checkpoint_slot_after_trailing_rapids():
    """Last target is the final vertex; trailing G0s must still fill every slot."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = _flat_tool()
    n_cut = 80
    n_rapid = 4
    n_verts = n_cut + n_rapid
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for i in range(n_verts):
        positions.extend((-10.0 + i * 0.2, 0.0, -1.0))
        vertex_types.append(2.0 if i == 0 or i >= n_cut else 1.0)
        tools.append(1)

    slots = 8
    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=slots, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        store = sim._checkpoints
        assert store is not None
        assert store.target_count == slots
        assert store._targets[-1] == n_verts - 1
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(lambda: len(sim._checkpoints) == slots, timeout=5.0)
        with sim._lock:
            assert len(sim._checkpoints) == store.target_count
            assert sim._checkpoints.vertices()[-1] == n_verts - 1
        stats = sim.hud_stats()
        assert stats is not None
        assert stats["checkpoint_count"] == stats["checkpoint_max_count"] == slots
        assert stats["checkpoint_head_vertex"] == n_verts - 1
    finally:
        sim.stop()


def test_idle_precompute_is_invisible_to_progress_and_mesh_callbacks():
    """Idle must not call on_progress / on_meshes_ready."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 150
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-7.5, dx=0.1)

    progress_calls = []
    mesh_calls = []

    sim = StockSimulator(
        on_progress=lambda v: progress_calls.append(v),
        on_meshes_ready=lambda m: mesh_calls.append(m),
        mesh_throttle_s=0.01,
    )
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: len(mesh_calls) > 0, timeout=1.0)
        time.sleep(0.05)
        progress_calls.clear()
        mesh_calls.clear()

        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(lambda: sim.bake_grid is not None and not sim.bake_grid.is_solid_at_world(7.0, 0.0, -0.5))
        time.sleep(sim._mesh_throttle_s * 3)

        assert progress_calls == []
        assert mesh_calls == []
        assert sim.carved_vertex == 0
    finally:
        sim.stop()


def test_idle_precompute_is_preempted_by_real_work():
    """A submit_range()/submit_recarve_to() call must not sit in the queue
    behind an in-flight idle precompute job — the idle job should yield at
    the next segment boundary instead of running to completion first."""
    import threading

    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.simulator.carvers.voxel import backend as voxel_backend

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )

    n_steps = 300
    xs = [-15.0 + i * 0.1 for i in range(n_steps + 1)]
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for x in xs:
        positions.extend((x, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0

    class _ProgressWaiter:
        def __init__(self):
            self._event = threading.Event()
            self._target = None
            self._lock = threading.Lock()

        def on_progress(self, vertex):
            with self._lock:
                if self._target is not None and vertex == self._target:
                    self._event.set()

        def wait_for(self, target, timeout=10.0):
            with self._lock:
                self._target = target
                self._event.clear()
            if not self._event.wait(timeout):
                raise AssertionError(f"timed out waiting for stock sim progress={target}")

    waiter = _ProgressWaiter()
    call_count = {"n": 0}
    original_carve = voxel_backend.carve_segment_into_grid

    def slow_counting_carve(grid, p0, p1, tool_def, tool_unit_scale=1.0, **kwargs):
        call_count["n"] += 1
        time.sleep(0.003)
        return original_carve(grid, p0, p1, tool_def, tool_unit_scale=tool_unit_scale, **kwargs)

    sim = StockSimulator(on_progress=waiter.on_progress, mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)

        voxel_backend.carve_segment_into_grid = slow_counting_carve
        try:
            sim.submit_idle_precompute(0)
            time.sleep(0.05)  # let a handful of slow segments carve

            start = time.monotonic()
            sim.submit_range(0, 20)
            waiter.wait_for(20, timeout=5.0)
            elapsed = time.monotonic() - start
        finally:
            voxel_backend.carve_segment_into_grid = original_carve

        # If the idle job weren't pre-empted it would have to reach the end
        # of the 300-vertex range first (~0.9s at 3ms/segment) before the
        # real 20-vertex request could even start.
        assert elapsed < 0.5
        # ...and it must not have been left to quietly run to completion.
        assert call_count["n"] < 150
        # The real request must still have gone through correctly (segments
        # 1..20 sweep x from -15.0 to -13.0 at y=0, z=-1).
        assert not sim.grid.is_solid_at_world(-14.0, 0.0, -0.5)
    finally:
        sim.stop()


def test_seek_forward_past_existing_checkpoint_jumps_instead_of_recarving():
    """Regression test: scrubbing back then forward again must reuse the
    checkpoint ahead of the new position instead of re-carving everything
    from the current (lower) playhead one segment at a time.
    """
    import threading

    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.simulator.carvers.voxel import backend as voxel_backend

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )

    n_steps = 500
    xs = [-15.0 + i * 0.1 for i in range(n_steps + 1)]
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for x in xs:
        positions.extend((x, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0  # first vertex is a rapid / path start, not a cut

    class _ProgressWaiter:
        def __init__(self):
            self._event = threading.Event()
            self._target = None
            self._lock = threading.Lock()

        def on_progress(self, vertex):
            with self._lock:
                if self._target is not None and vertex == self._target:
                    self._event.set()

        def wait_for(self, target, timeout=10.0):
            with self._lock:
                self._target = target
                self._event.clear()
            if not self._event.wait(timeout):
                raise AssertionError(f"timed out waiting for stock sim progress={target}")

    waiter = _ProgressWaiter()
    call_count = {"n": 0}
    original_carve = voxel_backend.carve_segment_into_grid

    def counting_carve(grid, p0, p1, tool_def, tool_unit_scale=1.0, **kwargs):
        call_count["n"] += 1
        return original_carve(grid, p0, p1, tool_def, tool_unit_scale=tool_unit_scale, **kwargs)

    sim = StockSimulator(on_progress=waiter.on_progress, mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})

        voxel_backend.carve_segment_into_grid = counting_carve
        try:
            # Forward playback all the way to the end.
            sim.submit_range(0, n_steps)
            waiter.wait_for(n_steps)

            # A checkpoint should exist somewhere ahead of vertex 150 by now.
            with sim._lock:
                cp_before_jump = sim._checkpoints.best_at_or_before(n_steps)
            assert cp_before_jump is not None and cp_before_jump.vertex > 150

            # Scrub back, then forward past the checkpoint again.
            sim.submit_recarve_to(150)
            waiter.wait_for(150)

            call_count["n"] = 0
            sim.submit_range(150, n_steps)
            waiter.wait_for(n_steps)
        finally:
            voxel_backend.carve_segment_into_grid = original_carve

        # The jump must have restored the checkpoint and only carved the
        # remainder — never the whole (150, n_steps] range one segment at a
        # time (that would be n_steps - 150 == 350 calls).
        expected_calls = n_steps - cp_before_jump.vertex
        assert call_count["n"] == expected_calls
        assert call_count["n"] < (n_steps - 150) // 2

        # Final grid state must still match a plain, uninterrupted forward
        # carve — the shortcut must not change the result, only its cost.
        reference_grid = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5)
        for i in range(1, n_steps + 1):
            p0 = (positions[(i - 1) * 3], positions[(i - 1) * 3 + 1], positions[(i - 1) * 3 + 2])
            p1 = (positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
            carve_segment_into_grid(reference_grid, p0, p1, tool)
        expected, _ = reference_grid.snapshot_non_full()
        actual, _ = sim.grid.snapshot_non_full()

        _assert_snapshots_equal(actual, expected)
    finally:
        sim.stop()


def test_reset_applies_voxel_target_and_checkpoint_slots():
    """StockSimulator.reset() should honor quality presets for grid size + store."""

    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import pick_voxel_size_mm
    from carveracontroller.addons.stock.simulator.simulation_quality import (
        CHECKPOINT_SLOTS_BY_LEVEL,
        VOXEL_TARGET_BY_LEVEL,
    )

    bounds = StockBounds(min_x=0, min_y=0, min_z=-10, max_x=100, max_y=50, max_z=0)
    slots = CHECKPOINT_SLOTS_BY_LEVEL["high"]
    target = VOXEL_TARGET_BY_LEVEL["high"]
    expected_size = pick_voxel_size_mm(bounds, target=target)

    sim = StockSimulator()
    try:
        sim.reset(bounds, enable=True, voxel_target=target, checkpoint_slots=slots, carver_mode="voxel")
        time.sleep(0.05)
        assert sim.grid is not None
        assert abs(sim.grid.voxel_size - expected_size) < 1e-9
        assert sim._checkpoints.slot_count == slots
        assert sim._checkpoints.base_interval == 4
        assert sim._checkpoints.target_count == 0  # no toolpath yet
    finally:
        sim.stop()


def test_reset_seeds_cylindrical_occupancy():
    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.stock_shape import CylindricalStock

    bounds = StockBounds(min_x=-20, min_y=-20, min_z=-10, max_x=20, max_y=20, max_z=0)
    shape = CylindricalStock(diameter_mm=40, height_mm=10)
    sim = StockSimulator()
    try:
        sim.reset(bounds, enable=True, cell_size_mm=2.0, shape=shape, carver_mode="voxel")
        assert sim.grid is not None
        assert sim.grid.is_solid_at_world(0.0, 0.0, -5.0)
        assert not sim.grid.is_solid_at_world(-19.0, -19.0, -5.0)
    finally:
        sim.stop()


def test_hud_stats_report_voxel_and_checkpoints():

    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.simulator.simulation_quality import CHECKPOINT_SLOTS_BY_LEVEL

    bounds = StockBounds(min_x=0, min_y=0, min_z=-5, max_x=20, max_y=10, max_z=0)
    slots = CHECKPOINT_SLOTS_BY_LEVEL["low"]
    sim = StockSimulator()
    try:
        assert sim.hud_stats() is None
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=slots, carver_mode="voxel")
        # Initial surface emit may leave resimulating briefly set — wait for idle.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and sim.resimulating:
            time.sleep(0.01)
        stats = sim.hud_stats()
        assert stats is not None
        assert abs(stats["cell_size_mm"] - 0.5) < 1e-9
        assert stats["grid_nx"] == 40
        assert stats["grid_ny"] == 20
        assert stats["grid_nz"] == 10
        assert "grid_bytes" not in stats
        assert stats["checkpoint_count"] == 0
        assert stats["checkpoint_max_count"] == 0  # no path → no targets
        assert "checkpoint_bytes" not in stats
        assert "checkpoint_max_bytes" not in stats
        assert stats["checkpoint_head_vertex"] == 0
        assert stats["resimulating"] is False

        # Bind a short path — HUD denominator becomes effective target_count.
        positions = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 3.0, 0.0, 0.0, 4.0, 0.0, 0.0]
        sim.set_toolpath(positions, [2.0, 1.0, 1.0, 1.0, 1.0], [1, 1, 1, 1, 1], {})
        stats = sim.hud_stats()
        assert stats["checkpoint_max_count"] == sim._checkpoints.target_count
        assert 0 < stats["checkpoint_max_count"] < slots

        sim.disable()
        assert sim.hud_stats() is None
    finally:
        sim.stop()


def test_idle_bake_does_not_move_display_grid():
    """Idle precompute carves the bake grid only; display occupancy stays put."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )

    n_steps = 200
    xs = [-10.0 + i * 0.1 for i in range(n_steps + 1)]
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for x in xs:
        positions.extend((x, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0

    mesh_calls: list = []

    sim = StockSimulator(
        on_meshes_ready=lambda m: mesh_calls.append(m),
        mesh_throttle_s=0.01,
    )
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: len(mesh_calls) > 0, timeout=2.0)
        time.sleep(0.05)
        mesh_calls.clear()

        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        far_x = xs[150]
        assert _wait_until(lambda: sim.bake_grid is not None and not sim.bake_grid.is_solid_at_world(far_x, 0.0, -0.5))
        assert sim.carved_vertex == 0
        assert sim.grid.is_solid_at_world(far_x, 0.0, -0.5)
        time.sleep(0.05)
        assert mesh_calls == []
    finally:
        sim.stop()


def test_hud_stats_concurrent_with_carve_does_not_raise():
    """hud_stats iterates grid chunks under the simulator lock; carving must
    hold the same lock so concurrent HUD polls never hit RuntimeError.
    """

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )

    n_steps = 250
    xs = [-12.0 + i * 0.1 for i in range(n_steps + 1)]
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for x in xs:
        positions.extend((x, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.submit_range(0, n_steps)

        deadline = time.monotonic() + 5.0
        saw_stats = False
        while time.monotonic() < deadline:
            stats = sim.hud_stats()
            if stats is not None:
                saw_stats = True
                assert stats["grid_nx"] > 0
                assert stats["cell_size_mm"] > 0
            if not sim.grid.is_solid_at_world(xs[-2], 0.0, -0.5):
                break
            time.sleep(0.0)  # yield to worker
        assert saw_stats
        # Finish polling briefly after carve completes to stress the lock handoff.
        for _ in range(50):
            stats = sim.hud_stats()
            assert stats is None or stats["grid_nx"] > 0
    finally:
        sim.stop()


def test_try_mesh_and_emit_aborts_after_generation_bump():
    """Stale mesh emit must not callback once reset bumps generation."""
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)
    received: list[dict] = []

    sim = StockSimulator(on_meshes_ready=lambda meshes: received.append(meshes), mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="voxel")
        # Stop the worker so only our direct helper calls populate ``received``.
        sim.stop()
        backend = sim.backend
        assert backend is not None
        gen = sim.generation
        received.clear()

        # Happy path: matching generation emits a replace of the stock shell.
        dirty = sim._initial_surface_dirty_keys(backend)
        assert sim._try_mesh_and_emit(backend, dirty, gen, replace=True) is True
        assert received and "__replace__" in received[-1]

        # Bump generation as reset/disable/recarve would.
        with sim._lock:
            sim._generation += 1

        received.clear()
        assert sim._try_mesh_and_emit(backend, set(), gen, replace=True) is False
        assert received == []
    finally:
        sim.stop()


def test_try_mesh_and_emit_aborts_when_grid_replaced():
    """Meshing must not emit if the live grid object was swapped out."""
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)
    received: list[dict] = []

    sim = StockSimulator(on_meshes_ready=lambda meshes: received.append(meshes), mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="voxel")
        sim.stop()
        stale = sim.backend
        gen = sim.generation
        assert stale is not None
        received.clear()

        # Simulate reset replacing the backend and bumping generation.
        with sim._lock:
            sim._generation += 1
            sim._backend = type(stale)(bounds, 1.0)

        assert sim._try_mesh_and_emit(stale, {(0, 0, 0)}, gen, replace=False) is False
        assert received == []
    finally:
        sim.stop()


def test_copy_chunks_deep_copies_arrays_and_keeps_empty():
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_EMPTY, ChunkCoord

    grid = _small_grid(voxel=1.0)
    coord = ChunkCoord(0, 0, 0)
    arr = grid.get_or_create_chunk(coord)
    assert arr is not None
    arr[0, 0, 0] = 0
    empty_key = (0, 0, 1) if grid.n_chunks_z > 1 else (1, 0, 0)
    grid._chunks[empty_key] = CHUNK_EMPTY

    copied = grid.copy_chunks({coord.as_tuple(), empty_key})
    assert copied.get_chunk_state(empty_key) is CHUNK_EMPTY
    src = grid.get_chunk_state(coord)
    dst = copied.get_chunk_state(coord)
    assert isinstance(src, np.ndarray) and isinstance(dst, np.ndarray)
    assert src is not dst
    assert np.array_equal(src, dst)
    src[1, 1, 1] = 0
    assert dst[1, 1, 1] == 1


def test_mesh_copy_2ring_required_for_face_culling():
    """FULL 1-ring neighbour must see a carved 2-ring neighbour when remeshed.

    Layout along +X: EMPTY F | FULL N | dirty D. Meshing dirty∪1-ring remeshes N;
    face culling on N toward F needs F in the copy set. A 1-ring-only copy treats
    missing F as FULL and over-culls that wall.
    """
    from carveracontroller.addons.stock.simulator import _expand_dirty_with_neighbors
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord
    from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import mesh_dirty_chunks

    bounds = StockBounds(min_x=0, min_y=0, min_z=0, max_x=48, max_y=16, max_z=16)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    assert grid.n_chunks_x >= 3

    f_key, n_key, d_key = (0, 0, 0), (1, 0, 0), (2, 0, 0)
    grid._chunks[f_key] = CHUNK_EMPTY
    assert grid.get_chunk_state(n_key) is CHUNK_FULL

    d_arr = grid.get_or_create_chunk(ChunkCoord(*d_key))
    assert d_arr is not None
    # Clear the face against N so N also gets an exposed wall on the dirty side.
    d_arr[0, :, :] = 0

    dirty = {d_key}
    mesh_keys = _expand_dirty_with_neighbors(grid, dirty)
    assert n_key in mesh_keys
    assert f_key not in mesh_keys

    copy_keys = _expand_dirty_with_neighbors(grid, mesh_keys)
    assert f_key in copy_keys

    expected = mesh_dirty_chunks(grid, mesh_keys)
    got_2ring = mesh_dirty_chunks(grid.copy_chunks(copy_keys), mesh_keys)
    got_1ring = mesh_dirty_chunks(grid.copy_chunks(mesh_keys), mesh_keys)

    assert expected[n_key] is not None
    assert got_2ring[n_key] == expected[n_key]
    # 1-ring-only over-culls N's faces toward EMPTY F → fewer vertices.
    assert got_1ring[n_key] is not None
    assert len(got_1ring[n_key][0]) < len(expected[n_key][0])


def test_partial_mesh_copy_matches_live_dirty_meshes():
    """2-ring copy + 1-ring mesh matches meshing the live grid for a multi-chunk carve."""
    from carveracontroller.addons.stock.simulator import _expand_dirty_with_neighbors
    from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import mesh_dirty_chunks

    bounds = StockBounds(min_x=-10, min_y=-10, min_z=-8, max_x=10, max_y=10, max_z=0)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=3.0,
        flute_length=5.0,
        length=10.0,
    )
    dirty = carve_segment_into_grid(grid, (-6.0, 0.0, -2.0), (6.0, 0.0, -2.0), tool)
    assert len(dirty) >= 2

    mesh_keys = _expand_dirty_with_neighbors(grid, dirty)
    copy_keys = _expand_dirty_with_neighbors(grid, mesh_keys)
    expected = mesh_dirty_chunks(grid, mesh_keys)
    got = mesh_dirty_chunks(grid.copy_chunks(copy_keys), mesh_keys)
    assert got == expected


def test_try_mesh_and_emit_uses_partial_copy_result():
    """Worker emit path returns the same chunk meshes as a live 1-ring remesh."""
    from carveracontroller.addons.stock.simulator import (
        StockSimulator,
        _expand_dirty_with_neighbors,
    )
    from carveracontroller.addons.stock.simulator.carvers.voxel.mesher import mesh_dirty_chunks

    bounds = StockBounds(min_x=-10, min_y=-10, min_z=-8, max_x=10, max_y=10, max_z=0)
    received: list[dict] = []
    sim = StockSimulator(on_meshes_ready=lambda meshes: received.append(meshes), mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="voxel")
        sim.stop()
        backend = sim.backend
        grid = sim.grid
        assert backend is not None and grid is not None
        tool = ToolDefinition(
            number=1,
            tool_type=ToolType.FLAT_END_MILL,
            diameter=3.0,
            flute_length=5.0,
            length=10.0,
        )
        dirty = carve_segment_into_grid(grid, (-6.0, 0.0, -2.0), (6.0, 0.0, -2.0), tool)
        mesh_keys = _expand_dirty_with_neighbors(grid, dirty)
        expected = mesh_dirty_chunks(grid, mesh_keys)

        received.clear()
        assert sim._try_mesh_and_emit(backend, dirty, sim.generation, replace=False) is True
        assert len(received) == 1
        assert received[0] == expected
    finally:
        sim.stop()


def test_inch_tool_unit_scale_matches_mm_kerf():
    """Inch tool tables stay in file units; carve must multiply (z,r) by 25.4."""
    from carveracontroller.addons.stock.simulator import _resolve_profile

    inch_tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=0.25,
        flute_length=0.5,
        length=1.0,
    )
    mm_tool = ToolDefinition(
        number=2,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=6.35,
        flute_length=12.7,
        length=25.4,
    )

    inch_profile = _resolve_profile(inch_tool, tool_unit_scale=25.4)
    mm_profile = _resolve_profile(mm_tool, tool_unit_scale=1.0)
    assert len(inch_profile) == len(mm_profile)
    for (zi, ri), (zm, rm) in zip(inch_profile, mm_profile):
        assert zi == pytest.approx(zm)
        assert ri == pytest.approx(rm)

    # Kerf on the same mm path must match (not the tiny unscaled inch diameter).
    grid_inch = _small_grid(voxel=0.5)
    grid_mm = _small_grid(voxel=0.5)
    carve_segment_into_grid(grid_inch, (-3.0, 0.0, -1.0), (3.0, 0.0, -1.0), inch_tool, tool_unit_scale=25.4)
    carve_segment_into_grid(grid_mm, (-3.0, 0.0, -1.0), (3.0, 0.0, -1.0), mm_tool, tool_unit_scale=1.0)
    # Near axis cleared; just outside Ø/2 (~3.175 mm) stays solid for both.
    assert not grid_inch.is_solid_at_world(0.0, 0.0, -0.5)
    assert not grid_mm.is_solid_at_world(0.0, 0.0, -0.5)
    assert grid_inch.is_solid_at_world(0.0, 3.5, -0.5)
    assert grid_mm.is_solid_at_world(0.0, 3.5, -0.5)
    assert not grid_inch.is_solid_at_world(0.0, 2.5, -0.5)
    assert not grid_mm.is_solid_at_world(0.0, 2.5, -0.5)

    # Passing scale= into tool_profile alone must NOT be treated as inch→mm.
    unscaled = _resolve_profile(inch_tool, tool_unit_scale=1.0)
    assert unscaled[-1][1] == pytest.approx(0.125)


def test_set_toolpath_tool_scale_reaches_carve():
    """StockSimulator.set_toolpath(tool_scale=) must scale kerf end-to-end."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-10, min_z=-5, max_x=10, max_y=10, max_z=0)
    inch_tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=0.25,
        flute_length=0.5,
        length=1.0,
    )
    positions = [-3.0, 0.0, -1.0, 3.0, 0.0, -1.0]
    vertex_types = [2.0, 1.0]
    tools = [1, 1]

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=4, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: inch_tool}, tool_scale=25.4)
        sim.submit_range(0, 1)
        assert _wait_until(lambda: not sim.grid.is_solid_at_world(0.0, 0.0, -0.5))
        assert sim.grid.is_solid_at_world(0.0, 3.5, -0.5)
        assert not sim.grid.is_solid_at_world(0.0, 2.5, -0.5)
    finally:
        sim.stop()


def test_idle_then_idle_preserves_delta_checkpoint_integrity():
    """Idle finish must not clear changed_since_cp; a later continue-without-restore
    P-frame must still restore to a full reference carve.
    """
    import threading

    import carveracontroller.addons.stock.simulator.worker as sim_module
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-25, min_y=-5, min_z=-5, max_x=25, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )

    n_steps = 200
    xs = [-10.0 + i * 0.1 for i in range(n_steps + 1)]
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for x in xs:
        positions.extend((x, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0

    # One vertex per job so the gate can pause after CP1 without a merged
    # chord landing on CP2 in the same carve.
    original_span = sim_module._MERGE_MAX_SPAN
    sim_module._MERGE_MAX_SPAN = 1
    paused = threading.Event()
    resume = threading.Event()
    released = threading.Event()
    original_iter = sim_module.StockSimulator._iter_cut_jobs

    def gated_iter(self, *args, **kwargs):
        for seg in original_iter(self, *args, **kwargs):
            yield seg
            if paused.is_set():
                continue
            store = self._checkpoints
            if len(store) != 1:
                continue
            first_v = store._items[0].vertex
            if self._bake_carved_vertex > first_v + 10:
                paused.set()
                resume.wait(timeout=5.0)
                released.set()

    sim = StockSimulator(mesh_throttle_s=0.01)
    sim_module.StockSimulator._iter_cut_jobs = gated_iter
    try:
        # Four slots → targets near 50/100/150/200; second CP is a delta P-frame.
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=4, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)

        sim.submit_idle_precompute(0)
        assert paused.wait(timeout=5.0)
        with sim._lock:
            first_v = sim._checkpoints._items[0].vertex
            assert len(sim._checkpoints) == 1
            assert sim._bake_carved_vertex > first_v + 10
        sim.cancel_idle_precompute()
        carved_after_cancel = sim.bake_carved_vertex
        resume.set()
        assert released.wait(timeout=5.0)
        with sim._lock:
            assert sim._bake_carved_vertex >= carved_after_cancel
            assert len(sim._checkpoints) == 1
            assert sim._grid_carved_vertex == 0

        # Resume bake; each idle job restores the last bookmark then continues.
        sim.submit_idle_precompute(first_v)
        assert _wait_until(lambda: len(sim._checkpoints) >= 2, timeout=10.0)
        with sim._lock:
            second_cp = sim._checkpoints._items[1]
            second_v = second_cp.vertex
            assert not second_cp.is_base
            restored = sim._checkpoints.resolve_chunks(second_cp, sim.grid.chunk_size)

        reference = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5)
        for i in range(1, second_v + 1):
            if vertex_types[i] > 1.5:
                continue
            p0 = (positions[(i - 1) * 3], positions[(i - 1) * 3 + 1], positions[(i - 1) * 3 + 2])
            p1 = (positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
            carve_segment_into_grid(reference, p0, p1, tool)
        expected, _ = reference.snapshot_non_full()

        restored_grid = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5)
        restored_grid.restore_non_full(restored)
        actual, _ = restored_grid.snapshot_non_full()
        assert set(actual.keys()) == set(expected.keys())
        for key in expected:
            exp = expected[key]
            got = actual[key]
            if hasattr(exp, "shape"):
                assert np.array_equal(got, exp), f"chunk {key} mismatch after idle→idle P-frame"
            else:
                assert got is exp
    finally:
        resume.set()
        sim_module.StockSimulator._iter_cut_jobs = original_iter
        sim_module._MERGE_MAX_SPAN = original_span
        sim.stop()


def test_next_unrecorded_target_peeks_maybe_record_gate():
    from carveracontroller.addons.stock.simulator import CheckpointStore

    store = CheckpointStore(slot_count=4)
    store.set_path_vertex_count(101)  # targets 25, 50, 75, 100
    assert store.next_unrecorded_target() == 25
    grid = _small_grid(voxel=1.0)
    tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=2.0, flute_length=3.0, length=8.0)
    carve_segment_into_grid(grid, (-2.0, 0.0, -1.0), (2.0, 0.0, -1.0), tool)
    assert store.maybe_record(25, grid, changed_keys=set())
    assert store.next_unrecorded_target() == 50
    assert store.maybe_record(50, grid, changed_keys=set())
    assert store.next_unrecorded_target() == 75


def test_clamp_collinear_run_end_binary_searches_longest_valid_prefix():
    # Shallow sine bulge: greedy local extend can overshoot, final sagitta is 0.5.
    # With voxel=1 → tol=0.25, the full chord must be clamped.
    import math

    from carveracontroller.addons.stock.simulator import (
        _MERGE_TOL_VOXEL_FRAC,
        _clamp_collinear_run_end,
        _point_to_segment_dist_sq,
    )

    n = 21
    pts = []
    for i in range(n):
        x = float(i)
        y = 0.5 * math.sin(math.pi * x / (n - 1))
        pts.append((x, y, -1.0))

    def point_at(idx: int):
        return pts[idx]

    tol = _MERGE_TOL_VOXEL_FRAC * 1.0
    end, p1 = _clamp_collinear_run_end(point_at, 1, n - 1, pts[0], tol)
    assert end < n - 1
    assert p1 == pts[end]
    tol_sq = tol * tol
    for k in range(1, end):
        assert _point_to_segment_dist_sq(pts[0], p1, pts[k]) <= tol_sq + 1e-12
    # One step longer must violate (otherwise binary search would have grown).
    if end + 1 < n:
        p_longer = pts[end + 1]
        assert any(_point_to_segment_dist_sq(pts[0], p_longer, pts[k]) > tol_sq for k in range(1, end + 1))


def test_iter_cut_jobs_clamps_greedy_arc_drift():
    """Gentle arc: local extend may accept a long run; final chord clamp splits it."""
    import math

    from carveracontroller.addons.stock.simulator import (
        _MERGE_TOL_VOXEL_FRAC,
        CheckpointStore,
        PathSnapshot,
        StockSimulator,
        _point_to_segment_dist_sq,
    )

    tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=2.0, flute_length=3.0, length=8.0)
    n = 21
    positions: list[float] = []
    for i in range(n):
        x = float(i)
        y = 0.5 * math.sin(math.pi * x / (n - 1))
        positions.extend((x, y, -1.0))
    path = PathSnapshot(positions, [2.0] + [1.0] * (n - 1), [1] * n, {1: tool}, tool_scale=1.0)
    store = CheckpointStore(slot_count=1)
    store.set_path_vertex_count(n)
    voxel = 1.0
    tol = _MERGE_TOL_VOXEL_FRAC * voxel
    tol_sq = tol * tol

    sim = StockSimulator()
    try:
        jobs = list(sim._iter_cut_jobs(path, 0, n - 1, voxel_size_mm=voxel, checkpoints=store))
        assert len(jobs) > 1  # full arc must not collapse to one oversize chord
        prev = 0
        for job in jobs:
            end = job.end_vertex
            for k in range(prev + 1, end):
                pk = (positions[k * 3], positions[k * 3 + 1], positions[k * 3 + 2])
                assert _point_to_segment_dist_sq(job.p0, job.p1, pk) <= tol_sq + 1e-9
            prev = end
    finally:
        sim.stop()


def test_iter_cut_jobs_merges_collinear_and_breaks_on_rules():
    from carveracontroller.addons.stock.simulator import (
        CheckpointStore,
        PathSnapshot,
        StockSimulator,
        _can_extend_collinear_merge,
    )

    tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=2.0, flute_length=3.0, length=8.0)
    tool2 = ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=2.0, flute_length=3.0, length=8.0)

    # Exact collinear along +X: vertices 0..8. One checkpoint slot at the end
    # so merging is not interrupted mid-path.
    positions = []
    for x in range(9):
        positions.extend((float(x), 0.0, -1.0))
    vertex_types = [2.0] + [1.0] * 8
    tools = [1] * 9
    path = PathSnapshot(positions, vertex_types, tools, {1: tool, 2: tool2}, tool_scale=1.0)

    store = CheckpointStore(slot_count=1)
    store.set_path_vertex_count(9)  # only target = 8
    sim = StockSimulator()
    try:
        jobs = list(sim._iter_cut_jobs(path, 0, 8, voxel_size_mm=1.0, checkpoints=store))
        assert len(jobs) == 1
        assert jobs[0].p0 == (0.0, 0.0, -1.0)
        assert jobs[0].p1 == (8.0, 0.0, -1.0)
        assert jobs[0].end_vertex == 8
    finally:
        sim.stop()

    # Sharp corner breaks merge
    assert not _can_extend_collinear_merge((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), tol_mm=0.25)
    # Reverse fold breaks
    assert not _can_extend_collinear_merge((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 0.0, 0.0), tol_mm=0.25)
    # Exact collinear extends
    assert _can_extend_collinear_merge((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), tol_mm=0.25)

    # Tool change breaks
    positions2 = []
    for x in range(5):
        positions2.extend((float(x), 0.0, -1.0))
    types2 = [2.0, 1.0, 1.0, 1.0, 1.0]
    tools2 = [1, 1, 1, 2, 2]
    path2 = PathSnapshot(positions2, types2, tools2, {1: tool, 2: tool2}, tool_scale=1.0)
    store2 = CheckpointStore(slot_count=1)
    store2.set_path_vertex_count(5)
    sim2 = StockSimulator()
    try:
        jobs2 = list(sim2._iter_cut_jobs(path2, 0, 4, voxel_size_mm=1.0, checkpoints=store2))
        assert [j.end_vertex for j in jobs2] == [2, 4]
        assert jobs2[0].tool_def is tool
        assert jobs2[1].tool_def is tool2
    finally:
        sim2.stop()

    # Rapid breaks
    positions3 = []
    for x in range(5):
        positions3.extend((float(x), 0.0, -1.0))
    types3 = [2.0, 1.0, 1.0, 2.0, 1.0]  # rapid into vertex 3
    tools3 = [1] * 5
    path3 = PathSnapshot(positions3, types3, tools3, {1: tool}, tool_scale=1.0)
    store3 = CheckpointStore(slot_count=1)
    store3.set_path_vertex_count(5)
    sim3 = StockSimulator()
    try:
        jobs3 = list(sim3._iter_cut_jobs(path3, 0, 4, voxel_size_mm=1.0, checkpoints=store3))
        assert [j.end_vertex for j in jobs3] == [2, 4]
    finally:
        sim3.stop()


def test_iter_cut_jobs_breaks_at_next_unrecorded_checkpoint_target():
    from carveracontroller.addons.stock.simulator import (
        CheckpointStore,
        PathSnapshot,
        StockSimulator,
    )

    tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=2.0, flute_length=3.0, length=8.0)
    n = 21
    positions = []
    for x in range(n):
        positions.extend((float(x) * 0.5, 0.0, -1.0))
    vertex_types = [2.0] + [1.0] * (n - 1)
    tools = [1] * n
    path = PathSnapshot(positions, vertex_types, tools, {1: tool}, tool_scale=1.0)

    store = CheckpointStore(slot_count=4)
    store.set_path_vertex_count(n)  # targets ~5,10,15,20
    assert store.next_unrecorded_target() == 5

    sim = StockSimulator()
    grid = _small_grid(voxel=0.5)
    try:
        # Simulate worker interleaving: yield → maybe_record → continue.
        ends = []
        from_v = 0
        while from_v < n - 1:
            jobs = list(sim._iter_cut_jobs(path, from_v, n - 1, voxel_size_mm=0.5, checkpoints=store))
            assert jobs
            job = jobs[0]
            ends.append(job.end_vertex)
            store.maybe_record(job.end_vertex, grid, changed_keys=set())
            from_v = job.end_vertex
            if len(ends) >= 4:
                break
        assert ends == [5, 10, 15, 20]
    finally:
        sim.stop()


def test_iter_cut_jobs_respects_max_span_cap(monkeypatch):
    import carveracontroller.addons.stock.simulator.worker as sim_module
    from carveracontroller.addons.stock.simulator import (
        CheckpointStore,
        PathSnapshot,
        StockSimulator,
    )

    monkeypatch.setattr(sim_module, "_MERGE_MAX_SPAN", 3)
    monkeypatch.setattr(sim_module, "_MERGE_MAX_MM_FLOOR", 1000.0)

    tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=2.0, flute_length=3.0, length=8.0)
    positions = []
    for x in range(10):
        positions.extend((float(x), 0.0, -1.0))
    path = PathSnapshot(positions, [2.0] + [1.0] * 9, [1] * 10, {1: tool}, tool_scale=1.0)
    # Single end-of-path target so span caps are what split the run.
    store = CheckpointStore(slot_count=1)
    store.set_path_vertex_count(10)
    sim = StockSimulator()
    try:
        jobs = list(sim._iter_cut_jobs(path, 0, 9, voxel_size_mm=1.0, checkpoints=store))
        spans = [j.end_vertex for j in jobs]
        assert spans == [3, 6, 9]
    finally:
        sim.stop()


def test_merged_exact_collinear_matches_polyline_carve():
    """Exact collinear polyline vs single chord → identical occupancy."""
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=15, max_y=5, max_z=0)
    grid_poly = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    grid_chord = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)

    xs = [float(i) for i in range(11)]
    for i in range(1, len(xs)):
        carve_segment_into_grid(grid_poly, (xs[i - 1], 0.0, -1.0), (xs[i], 0.0, -1.0), tool)
    carve_segment_into_grid(grid_chord, (xs[0], 0.0, -1.0), (xs[-1], 0.0, -1.0), tool)

    snap_a, _ = grid_poly.snapshot_non_full()
    snap_b, _ = grid_chord.snapshot_non_full()
    assert set(snap_a.keys()) == set(snap_b.keys())
    for key in snap_a:
        a, b = snap_a[key], snap_b[key]
        if hasattr(a, "shape"):
            assert np.array_equal(a, b), f"chunk {key} mismatch"
        else:
            assert a is b


def test_carve_early_out_leaves_far_full_chunks_unallocated():
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_FULL, ChunkCoord

    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=12.0,  # tall flute → loose AABB oversweeps Z
        length=20.0,
    )
    # Larger stock so AABB visits chunks that the tighter reject should skip.
    bounds = StockBounds(min_x=-20, min_y=-20, min_z=-20, max_x=20, max_y=20, max_z=0)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=1.0, chunk_size=8)

    carve_segment_into_grid(grid, (-1.0, 0.0, -1.0), (1.0, 0.0, -1.0), tool)

    # A chunk well beside the cut in XY must remain absent/FULL (never materialised).
    far = ChunkCoord(cx=grid.n_chunks_x - 1, cy=0, cz=0)
    assert grid.get_chunk_state(far) is CHUNK_FULL or far.as_tuple() not in grid._chunks
    # And it should not appear as an allocated array.
    assert not isinstance(grid.get_chunk_state(far), np.ndarray)


def test_dense_and_sparse_carve_branches_agree():
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)

    # Pre-carve a pocket so later solid fraction is low enough for sparse relevance.
    grid_seed = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    carve_segment_into_grid(grid_seed, (-3.0, 0.0, -1.0), (3.0, 0.0, -1.0), tool)
    seed, _ = grid_seed.snapshot_non_full()

    grid_dense = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    grid_dense.restore_non_full({k: (v.copy() if hasattr(v, "copy") else v) for k, v in seed.items()})
    grid_sparse = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    grid_sparse.restore_non_full({k: (v.copy() if hasattr(v, "copy") else v) for k, v in seed.items()})

    carve_segment_into_grid(grid_dense, (0.0, -2.0, -1.5), (0.0, 2.0, -1.5), tool, sparse_solid_frac=0.0)
    carve_segment_into_grid(grid_sparse, (0.0, -2.0, -1.5), (0.0, 2.0, -1.5), tool, sparse_solid_frac=1.0)

    snap_d, _ = grid_dense.snapshot_non_full()
    snap_s, _ = grid_sparse.snapshot_non_full()
    assert set(snap_d.keys()) == set(snap_s.keys())
    for key in snap_d:
        d, s = snap_d[key], snap_s[key]
        if hasattr(d, "shape"):
            assert np.array_equal(d, s), f"chunk {key} dense/sparse mismatch"
        else:
            assert d is s


def test_dense_z_slab_matches_sparse_on_shallow_slot():
    """Dense Z-slab must not drop a layer the full-chunk sparse path would clear."""
    tool = _flat_tool(diameter=2.0, flute_length=4.0)
    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)
    grid_dense = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    grid_sparse = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)

    p0, p1 = (-3.0, 0.0, -0.5), (3.0, 0.0, -0.5)
    carve_segment_into_grid(grid_dense, p0, p1, tool, sparse_solid_frac=0.0)
    carve_segment_into_grid(grid_sparse, p0, p1, tool, sparse_solid_frac=1.0)

    assert not grid_dense.is_solid_at_world(0.0, 0.0, -0.25)
    assert grid_dense.is_solid_at_world(0.0, 0.0, -4.5)

    snap_d, _ = grid_dense.snapshot_non_full()
    snap_s, _ = grid_sparse.snapshot_non_full()
    assert set(snap_d.keys()) == set(snap_s.keys())
    for key in snap_d:
        d, s = snap_d[key], snap_s[key]
        if hasattr(d, "shape"):
            assert np.array_equal(d, s), f"chunk {key} z-slab/sparse mismatch"
        else:
            assert d is s


def test_constant_radius_mask_matches_interpolator():
    """Flat-mill shortcut must match searchsorted on stationary, plunge, and XY moves."""
    from unittest.mock import patch

    from carveracontroller.addons.stock.simulator import (
        _constant_profile_radius,
        _max_profile_radius,
        _resolve_profile,
        _voxels_inside_tool,
    )

    profile = _resolve_profile(_flat_tool(diameter=2.0, flute_length=4.0))
    profile_zs = np.array([z for z, _r in profile], dtype=np.float64)
    profile_rs = np.array([r for _z, r in profile], dtype=np.float64)
    assert _constant_profile_radius(profile_rs) == pytest.approx(1.0)
    max_r = _max_profile_radius(profile)
    eps = 1e-9

    rng = np.random.default_rng(0)
    XX = np.concatenate([rng.uniform(-3.0, 3.0, 120), np.array([0.0, 1.0, 1.0 + 1e-6, 1.5], dtype=np.float64)])
    YY = np.concatenate([rng.uniform(-3.0, 3.0, 120), np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float64)])
    ZZ = np.concatenate([rng.uniform(-6.0, 2.0, 120), np.array([-1.0, -0.5, 0.5, -5.0], dtype=np.float64)])

    cases = (
        ((0.0, 0.0, -1.0), (0.0, 0.0, -1.0)),  # stationary
        ((0.0, 0.0, 0.0), (0.0, 0.0, -3.0)),  # plunge
        ((-2.0, 0.0, -1.0), (2.0, 0.0, -1.0)),  # XY move
    )

    def _mask(p0, p1):
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        return _voxels_inside_tool(
            XX,
            YY,
            ZZ,
            p0,
            dx,
            dy,
            dz,
            dx * dx + dy * dy + dz * dz,
            dx * dx + dy * dy,
            float(profile[0][0]),
            float(profile[-1][0]),
            profile,
            profile_zs,
            profile_rs,
            eps,
            max_r,
        )

    for p0, p1 in cases:
        fast = _mask(p0, p1)
        with patch(
            "carveracontroller.addons.stock.simulator.carvers.voxel.carve._constant_profile_radius",
            return_value=None,
        ):
            interpolated = _mask(p0, p1)
        assert np.array_equal(fast, interpolated), f"mismatch for segment {p0} -> {p1}"
        assert fast.any(), f"expected some hits for segment {p0} -> {p1}"


def test_mesh_updates_can_be_suppressed_while_carving_continues():
    """Playback should keep carving on the worker but defer mesh callbacks."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    n_steps = 40
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for i in range(n_steps + 1):
        positions.extend((-8.0 + i * 0.4, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0

    meshes_received: list[dict] = []

    def on_meshes(meshes):
        meshes_received.append(meshes)

    sim = StockSimulator(on_meshes_ready=on_meshes, mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=8, carver_mode="voxel")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        assert _wait_until(lambda: any("__replace__" in m for m in meshes_received), timeout=2.0)
        sim.set_mesh_updates_enabled(False)
        meshes_received.clear()
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.submit_range(0, n_steps)
        assert _wait_until(lambda: sim._grid_carved_vertex >= n_steps, timeout=5.0)
        # Allow a throttle window; suppressed mode must not emit carved meshes.
        time.sleep(0.2)
        assert meshes_received == []
        assert sim.grid is not None
        assert not sim.grid.is_solid_at_world(0.0, 0.0, -1.0)

        # Pause path: re-enable + flush patches visited chunks (not a full-shell replace).
        sim.set_mesh_updates_enabled(True)
        sim.request_mesh_flush()
        assert _wait_until(lambda: len(meshes_received) > 0, timeout=5.0)
        assert not any("__replace__" in m for m in meshes_received)
    finally:
        sim.stop()


def test_reset_and_disable_reenable_mesh_updates():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)
    sim = StockSimulator()
    try:
        sim.set_mesh_updates_enabled(False)
        assert sim._mesh_updates_enabled is False
        sim.reset(bounds, cell_size_mm=1.0, enable=True, checkpoint_slots=2, carver_mode="voxel")
        assert sim._mesh_updates_enabled is True
        sim.set_mesh_updates_enabled(False)
        sim.disable()
        assert sim._mesh_updates_enabled is True
    finally:
        sim.stop()


def test_idle_with_mesh_updates_on_still_bakes_checkpoints():
    """Idle bake records checkpoints without moving display occupancy or emitting meshes."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )
    n_steps = 40
    positions: list[float] = []
    vertex_types: list[float] = []
    tools: list[int] = []
    for i in range(n_steps + 1):
        positions.extend((-8.0 + i * 0.4, 0.0, -1.0))
        vertex_types.append(1.0)
        tools.append(1)
    vertex_types[0] = 2.0

    meshes_received: list[dict] = []
    checkpoint_lists: list[list[int]] = []

    def on_meshes(meshes):
        meshes_received.append(meshes)

    def on_checkpoints(verts):
        checkpoint_lists.append(list(verts))

    sim = StockSimulator(
        on_meshes_ready=on_meshes,
        on_checkpoints=on_checkpoints,
        mesh_throttle_s=0.05,
    )
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=8, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        meshes_received.clear()
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        assert sim._mesh_updates_enabled
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(lambda: sim.bake_carved_vertex >= n_steps, timeout=5.0)
        time.sleep(0.2)
        assert meshes_received == []
        assert sim.carved_vertex == 0
        assert sim.grid is not None
        assert sim.grid.is_solid_at_world(0.0, 0.0, -1.0)
        assert sim.bake_grid is not None
        assert not sim.bake_grid.is_solid_at_world(0.0, 0.0, -1.0)
        assert any(checkpoint_lists), "expected checkpoints during idle bake"
    finally:
        sim.stop()


def test_recarve_does_not_rearm_idle_bake():
    """Recarve must not start bake on its own; pause/tests submit idle explicitly."""

    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 40
    playhead = 10
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-8.0, dx=0.4)

    sim = StockSimulator(mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=8, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)
        sim.submit_recarve_to(playhead)
        assert _wait_until(lambda: not sim.resimulating, timeout=5.0)
        assert _wait_until(lambda: sim.carved_vertex >= playhead, timeout=2.0)
        time.sleep(0.2)
        assert sim.carved_vertex == playhead
        assert sim.bake_carved_vertex == 0
    finally:
        sim.stop()


def test_stop_clears_worker_when_idle():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=0, min_y=0, min_z=-5, max_x=10, max_y=10, max_z=0)
    sim = StockSimulator(mesh_throttle_s=0.01)
    sim.reset(bounds, cell_size_mm=1.0, enable=False, carver_mode="voxel")
    assert sim._worker is not None and sim._worker.is_alive()
    sim.stop()
    assert sim._worker is None


def test_stop_retains_worker_handle_when_join_times_out(monkeypatch):
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=0, min_y=0, min_z=-5, max_x=10, max_y=10, max_z=0)
    sim = StockSimulator(mesh_throttle_s=0.01)
    sim.reset(bounds, cell_size_mm=1.0, enable=False, carver_mode="voxel")
    worker = sim._worker
    assert worker is not None and worker.is_alive()

    monkeypatch.setattr(worker, "join", lambda timeout=None: None)
    monkeypatch.setattr(worker, "is_alive", lambda: True)

    sim.stop()
    assert sim._worker is worker

    # Restore real thread methods so cleanup can finish.
    monkeypatch.undo()
    sim.stop()
    assert sim._worker is None


def test_set_display_vertex_latest_wins_reaches_last_target():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 80
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-8.0, dx=0.2)

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        for v in range(1, n_steps + 1):
            sim.set_display_vertex(v)
        assert sim._queue.qsize() < 8
        assert _wait_until(lambda: sim.carved_vertex >= n_steps, timeout=5.0)
    finally:
        sim.stop()


def test_request_mesh_flush_does_not_replace_after_forward_session():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 30
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-8.0, dx=0.5)

    meshes_received: list[dict] = []

    sim = StockSimulator(on_meshes_ready=lambda m: meshes_received.append(m), mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        meshes_received.clear()
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_display_vertex(n_steps)
        assert _wait_until(lambda: sim.carved_vertex >= n_steps, timeout=5.0)
        meshes_received.clear()
        sim.request_mesh_flush()
        time.sleep(0.15)
        assert all("__replace__" not in m for m in meshes_received)
    finally:
        sim.stop()


def test_request_mesh_flush_emits_when_nothing_is_dirty():
    """Pause-with-AABB needs a callback even if there is nothing new to remesh."""
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-5, min_y=-5, min_z=-5, max_x=5, max_y=5, max_z=0)
    meshes_received: list[dict] = []

    sim = StockSimulator(on_meshes_ready=lambda m: meshes_received.append(m), mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="voxel")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        assert _wait_until(lambda: any("__replace__" in m for m in meshes_received), timeout=2.0)
        meshes_received.clear()
        sim.request_mesh_flush()
        assert _wait_until(lambda: len(meshes_received) > 0, timeout=2.0)
        assert all("__replace__" not in m and "__clear_all__" not in m for m in meshes_received)
    finally:
        sim.stop()


def test_set_display_vertex_backward_restores_stock_ahead_of_playhead():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 100
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-10.0, dx=0.2)

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=8, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_display_vertex(n_steps)
        assert _wait_until(lambda: sim.carved_vertex >= n_steps, timeout=5.0)
        far_x = -10.0 + 80 * 0.2
        assert not sim.grid.is_solid_at_world(far_x, 0.0, -0.5)

        sim.set_display_vertex(10)
        assert _wait_until(lambda: sim.grid.is_solid_at_world(far_x, 0.0, -0.5), timeout=5.0)
        assert sim.carved_vertex <= 10
    finally:
        sim.stop()


def test_idle_bake_does_not_advance_display_when_mesh_updates_enabled():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 40
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-8.0, dx=0.4)

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        assert sim._mesh_updates_enabled
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(lambda: sim.bake_carved_vertex >= n_steps, timeout=5.0)
        assert sim.carved_vertex == 0
        assert sim.grid.is_solid_at_world(0.0, 0.0, -1.0)
        assert sim.bake_grid is not None
        assert not sim.bake_grid.is_solid_at_world(0.0, 0.0, -1.0)
    finally:
        sim.stop()


def test_idle_does_not_advance_when_idle_ahead_disallowed():
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-10, min_y=-5, min_z=-5, max_x=10, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 40
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-8.0, dx=0.4)

    sim = StockSimulator(mesh_throttle_s=0.01)
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_mesh_updates_enabled(False)
        sim.set_idle_ahead_allowed(False)
        sim.submit_idle_precompute(0)
        time.sleep(0.2)
        assert sim.carved_vertex == 0
        assert sim.grid.is_solid_at_world(0.0, 0.0, -1.0)
        assert sim.bake_grid is None or sim.bake_carved_vertex == 0
    finally:
        sim.stop()


def test_display_follow_jumps_checkpoints_recorded_by_bake():
    """Bake-ahead bookmarks let the display grid skip the unplayed tail."""
    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.simulator.carvers.voxel import backend as voxel_backend

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 200
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-10.0, dx=0.1)

    sim = StockSimulator(mesh_throttle_s=0.01)
    call_count = {"n": 0}
    original_carve = voxel_backend.carve_segment_into_grid

    def counting_carve(grid, p0, p1, tool_def, tool_unit_scale=1.0, **kwargs):
        call_count["n"] += 1
        return original_carve(grid, p0, p1, tool_def, tool_unit_scale=tool_unit_scale, **kwargs)

    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=8, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert _wait_until(lambda: sim.bake_carved_vertex >= n_steps, timeout=5.0)
        with sim._lock:
            cp = sim._checkpoints.best_at_or_before(n_steps)
        assert cp is not None and cp.vertex > 50
        assert sim.carved_vertex == 0

        voxel_backend.carve_segment_into_grid = counting_carve
        try:
            sim.set_display_vertex(n_steps)
            assert _wait_until(lambda: sim.carved_vertex >= n_steps, timeout=5.0)
        finally:
            voxel_backend.carve_segment_into_grid = original_carve

        assert call_count["n"] < n_steps // 4
        far_x = -10.0 + 150 * 0.1
        assert not sim.grid.is_solid_at_world(far_x, 0.0, -0.5)
    finally:
        voxel_backend.carve_segment_into_grid = original_carve
        sim.stop()


def test_display_seek_back_rearms_idle_bake():
    """Scrubbing the playhead back must not leave bake stopped."""
    import threading

    import carveracontroller.addons.stock.simulator.worker as sim_module
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(min_x=-20, min_y=-5, min_z=-5, max_x=20, max_y=5, max_z=0)
    tool = _flat_tool()
    n_steps = 200
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-10.0, dx=0.1)

    paused = threading.Event()
    resume = threading.Event()
    original_iter = sim_module.StockSimulator._iter_cut_jobs

    def gated_iter(self, *args, **kwargs):
        for i, seg in enumerate(original_iter(self, *args, **kwargs)):
            yield seg
            # Pause between jobs (lock not held) so the test can seek without
            # racing a worker that would otherwise finish the path first.
            if i == 0 and not paused.is_set():
                paused.set()
                resume.wait(timeout=5.0)

    sim = StockSimulator(mesh_throttle_s=0.01)
    sim_module.StockSimulator._iter_cut_jobs = gated_iter
    try:
        sim.reset(bounds, cell_size_mm=0.5, enable=True, checkpoint_slots=8, carver_mode="voxel")
        _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_idle_ahead_allowed(True)
        sim.submit_idle_precompute(0)
        assert paused.wait(timeout=5.0)
        sim.set_display_vertex(10)
        resume.set()
        assert _wait_until(lambda: sim.carved_vertex == 10, timeout=5.0)
        assert _wait_until(lambda: sim.bake_carved_vertex >= n_steps, timeout=5.0)
        assert sim.carved_vertex == 10
    finally:
        resume.set()
        sim_module.StockSimulator._iter_cut_jobs = original_iter
        sim.stop()


def test_a0_zero_matches_upright_carve():
    tool = _flat_tool()
    g0 = _small_grid(voxel=0.5)
    g1 = _small_grid(voxel=0.5)
    carve_segment_into_grid(g0, (-3.0, 0.0, -1.0), (3.0, 0.0, -1.0), tool)
    carve_segment_into_grid(g1, (-3.0, 0.0, -1.0), (3.0, 0.0, -1.0), tool, a0=0.0, a1=0.0)
    assert g0.is_solid_at_world(0.0, 0.0, -0.75) == g1.is_solid_at_world(0.0, 0.0, -0.75)
    assert g0.is_solid_at_world(0.0, 4.0, -1.0) == g1.is_solid_at_world(0.0, 4.0, -1.0)


def test_indexed_a90_clears_side_not_top():
    from carveracontroller.addons.stock.stock_geometry import rotate_yz

    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    # Machine tip at Z=8; a point 2 mm up the flute is unambiguously inside.
    carve_segment_into_grid(grid, (20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=90.0, a1=90.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not grid.is_solid_at_world(20.0, y, z)
    assert grid.is_solid_at_world(20.0, 0.0, 10.0)


def test_wrapping_a_clears_arc():
    from carveracontroller.addons.stock.stock_geometry import rotate_yz

    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    grid = ChunkedVoxelGrid(bounds, voxel_size_mm=0.5, chunk_size=8)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    carve_segment_into_grid(grid, (20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=90.0)
    assert not grid.is_solid_at_world(20.0, 0.0, 10.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not grid.is_solid_at_world(20.0, y, z)


def test_iter_cut_jobs_merges_a_only_wrap():
    from carveracontroller.addons.stock.simulator import CheckpointStore, PathSnapshot, StockSimulator

    tool = _flat_tool()
    n = 10
    positions: list[float] = []
    angles: list[float] = []
    for i in range(n):
        positions.extend((20.0, 0.0, 8.0))
        angles.append(float(i * 5.0))
    path = PathSnapshot(
        positions,
        [2.0] + [1.0] * (n - 1),
        [1] * n,
        {1: tool},
        tool_scale=1.0,
        angles=angles,
    )
    store = CheckpointStore(slot_count=1)
    store.set_path_vertex_count(n)
    sim = StockSimulator()
    try:
        jobs = list(sim._iter_cut_jobs(path, 0, n - 1, voxel_size_mm=1.0, checkpoints=store))
        assert len(jobs) == 1
        assert jobs[0].a0 == pytest.approx(0.0)
        assert jobs[0].a1 == pytest.approx(45.0)
        assert jobs[0].p0 == (20.0, 0.0, 8.0)
        assert jobs[0].p1 == (20.0, 0.0, 8.0)
    finally:
        sim.stop()


def test_iter_cut_jobs_does_not_chord_wrapping_z_bump():
    """Constant-XY 4-axis following is XYZ-collinear; a Z bump must not collapse.

    Nefertiti-style wrapping keeps X (and Y) fixed while Z tracks the surface
    and A advances. A machine-XYZ chord overcuts the ridge and leaves holes.
    """
    from carveracontroller.addons.stock.simulator import CheckpointStore, PathSnapshot, StockSimulator

    tool = _flat_tool()
    # Slow Z, then a jump: linear Z(A) would be far from the second vertex.
    zs = [10.0, 10.2, 11.5, 12.0]
    angs = [0.0, 2.0, 4.0, 6.0]
    positions: list[float] = []
    for z in zs:
        positions.extend((20.0, 0.0, z))
    n = len(zs)
    path = PathSnapshot(
        positions,
        [2.0] + [1.0] * (n - 1),
        [1] * n,
        {1: tool},
        tool_scale=1.0,
        angles=angs,
    )
    store = CheckpointStore(slot_count=1)
    store.set_path_vertex_count(n)
    sim = StockSimulator()
    try:
        jobs = list(sim._iter_cut_jobs(path, 0, n - 1, voxel_size_mm=0.2, checkpoints=store))
        assert len(jobs) >= 2
        assert not (len(jobs) == 1 and jobs[0].p0[2] == pytest.approx(10.0) and jobs[0].p1[2] == pytest.approx(12.0))
    finally:
        sim.stop()


def test_iter_cut_jobs_merges_linear_wrapping_z_ramp():
    """Linear Z vs A at constant XY is a true helix and may stay one job."""
    from carveracontroller.addons.stock.simulator import CheckpointStore, PathSnapshot, StockSimulator

    tool = _flat_tool()
    zs = [10.0, 11.0, 12.0, 13.0]
    angs = [0.0, 2.0, 4.0, 6.0]
    positions: list[float] = []
    for z in zs:
        positions.extend((20.0, 0.0, z))
    n = len(zs)
    path = PathSnapshot(
        positions,
        [2.0] + [1.0] * (n - 1),
        [1] * n,
        {1: tool},
        tool_scale=1.0,
        angles=angs,
    )
    store = CheckpointStore(slot_count=1)
    store.set_path_vertex_count(n)
    sim = StockSimulator()
    try:
        jobs = list(sim._iter_cut_jobs(path, 0, n - 1, voxel_size_mm=0.2, checkpoints=store))
        assert len(jobs) == 1
        assert jobs[0].p0[2] == pytest.approx(10.0)
        assert jobs[0].p1[2] == pytest.approx(13.0)
        assert jobs[0].a0 == pytest.approx(0.0)
        assert jobs[0].a1 == pytest.approx(6.0)
    finally:
        sim.stop()


def test_reset_seeds_rotary_cylindrical_occupancy():
    from carveracontroller.addons.stock.simulator import StockSimulator
    from carveracontroller.addons.stock.stock_geometry import compute_wcs_bounds
    from carveracontroller.addons.stock.stock_origin import CORNER_LC, Z_CENTER, StockOrigin
    from carveracontroller.addons.stock.stock_shape import RotaryCylindricalStock

    shape = RotaryCylindricalStock(diameter_mm=40, length_mm=80)
    bounds = compute_wcs_bounds(shape, StockOrigin(xy_corner=CORNER_LC, z_reference=Z_CENTER))
    sim = StockSimulator()
    try:
        sim.reset(bounds, enable=True, cell_size_mm=2.0, shape=shape, carver_mode="voxel")
        assert sim.grid is not None
        assert sim.grid.is_solid_at_world(40.0, 0.0, 0.0)
        assert not sim.grid.is_solid_at_world(40.0, 19.0, 19.0)
    finally:
        sim.stop()


def test_take_pending_mesh_keys_caps_and_flush_takes_all():
    from carveracontroller.addons.stock.simulator.worker import _take_pending_mesh_keys

    pending = {(2, 0, 0), (0, 0, 0), (1, 0, 0), (3, 0, 0)}
    batch = _take_pending_mesh_keys(pending, unlimited=False, cap=2)
    assert len(batch) == 2
    assert batch == {(0, 0, 0), (1, 0, 0)}
    assert pending == {(2, 0, 0), (3, 0, 0)}
    rest = _take_pending_mesh_keys(pending, unlimited=True, cap=2)
    assert rest == {(2, 0, 0), (3, 0, 0)}
    assert pending == set()


def test_take_pending_mesh_keys_prefers_connected_blob_around_tool():
    from carveracontroller.addons.stock.simulator.worker import _take_pending_mesh_keys

    pending = {(0, 0, 0), (10, 0, 0), (11, 0, 0), (12, 0, 0)}
    batch = _take_pending_mesh_keys(pending, unlimited=False, cap=2, around=(11, 0, 0))
    assert batch == {(10, 0, 0), (11, 0, 0)} or batch == {(11, 0, 0), (12, 0, 0)}
    assert (11, 0, 0) in batch
    assert (0, 0, 0) not in batch
    assert (0, 0, 0) in pending


def test_take_pending_mesh_keys_fills_cap_from_nearest_leftover():
    """After the live blob, leftover tiles nearest the tool fill the rest of the cap."""
    from carveracontroller.addons.stock.simulator.worker import _take_pending_mesh_keys

    pending = {(0, 0, 0), (8, 0, 0), (9, 0, 0)}
    batch = _take_pending_mesh_keys(pending, unlimited=False, cap=2, around=(0, 0, 0))
    assert batch == {(0, 0, 0), (8, 0, 0)}
    assert pending == {(9, 0, 0)}


def test_play_mesh_throttle_matches_pause():
    from carveracontroller.addons.stock.simulator import DEFAULT_MESH_THROTTLE_S, PLAY_MESH_THROTTLE_S

    assert PLAY_MESH_THROTTLE_S == DEFAULT_MESH_THROTTLE_S
    assert PLAY_MESH_THROTTLE_S <= 0.15


def test_mesh_flush_emits_all_dirty_tiles(monkeypatch):
    import carveracontroller.addons.stock.simulator.worker as worker_mod
    from carveracontroller.addons.stock.simulator import StockSimulator

    monkeypatch.setattr(worker_mod, "MAX_MESH_TILES_PER_EMIT", 1)
    bounds = StockBounds(min_x=-20, min_y=-8, min_z=-5, max_x=20, max_y=8, max_z=0)
    tool = _flat_tool(diameter=4.0, flute_length=6.0)
    n_steps = 80
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-16.0, dx=0.4)
    flush_dirty: list[int] = []

    sim = StockSimulator(on_meshes_ready=lambda _m: None, mesh_throttle_s=0.02)
    orig = sim._try_mesh_and_emit

    def _count(backend, dirty, gen, *, replace, force_emit=False):
        if force_emit:
            flush_dirty.append(len(dirty))
        return orig(backend, dirty, gen, replace=replace, force_emit=force_emit)

    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="voxel")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim._try_mesh_and_emit = _count  # type: ignore[method-assign]
        sim.set_mesh_updates_enabled(False)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.set_display_vertex(n_steps)
        assert _wait_until(lambda: sim.carved_vertex >= n_steps, timeout=5.0)
        flush_dirty.clear()
        sim.set_mesh_updates_enabled(True)
        sim.request_mesh_flush()
        assert _wait_until(lambda: any(n > 1 for n in flush_dirty), timeout=5.0)
    finally:
        sim.stop()


def test_paused_scrub_emits_mesh_before_idle_bake(monkeypatch):
    """Pause/scrub must remesh immediately; idle bake must not swallow the emit."""
    import carveracontroller.addons.stock.simulator.worker as worker_mod
    from carveracontroller.addons.stock.simulator import StockSimulator

    monkeypatch.setattr(worker_mod, "MAX_MESH_TILES_PER_EMIT", 1)
    bounds = StockBounds(min_x=-20, min_y=-8, min_z=-5, max_x=20, max_y=8, max_z=0)
    tool = _flat_tool(diameter=4.0, flute_length=6.0)
    n_steps = 80
    positions, vertex_types, tools = _linear_x_toolpath(n_steps, x0=-16.0, dx=0.4)
    patches: list[dict] = []

    def _is_patch(meshes: dict) -> bool:
        return bool(meshes) and "__replace__" not in meshes and "__clear_all__" not in meshes

    # Throttle longer than the wait: without pause-immediate emit this would hang.
    sim = StockSimulator(on_meshes_ready=lambda m: patches.append(dict(m)), mesh_throttle_s=5.0)
    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="voxel")
        assert _wait_until(lambda: not sim.resimulating, timeout=2.0)
        sim.set_idle_ahead_allowed(True)
        sim.set_toolpath(positions, vertex_types, tools, {1: tool})
        sim.submit_idle_precompute(0)
        patches.clear()
        sim.set_display_vertex(n_steps)
        assert _wait_until(lambda: sim.carved_vertex >= n_steps, timeout=5.0)
        assert _wait_until(lambda: any(_is_patch(m) for m in patches), timeout=2.0)

        patches.clear()
        sim.set_display_vertex(10)
        far_x = -16.0 + 70 * 0.4
        assert _wait_until(lambda: sim.grid.is_solid_at_world(far_x, 0.0, -0.5), timeout=5.0)
        assert _wait_until(lambda: any(_is_patch(m) for m in patches), timeout=2.0)
    finally:
        sim.stop()
