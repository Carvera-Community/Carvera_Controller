"""Idle laser batching in StockSimulator._carve_segments_to."""

from __future__ import annotations

from unittest.mock import MagicMock

from carveracontroller.addons.stock.simulator import CheckpointStore, PathSnapshot, StockSimulator
from carveracontroller.addons.stock.simulator.worker import CarveJob
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType
from carveracontroller.CNC import LASER_TOOL_NUMBER


def _flat_tool():
    return ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=2.0,
        flute_length=4.0,
        length=10.0,
    )


def _mock_backend(laser_batches: list[list[int]], mill_batches: list[list[int]] | None = None):
    backend = MagicMock()
    backend.cell_size = 1.0
    grid = MagicMock()
    grid.snapshot_non_full.return_value = ({}, 0)
    backend.grid = grid
    if mill_batches is None:
        mill_batches = []

    def engrave_segments(strokes, tool_unit_scale=1.0):
        del tool_unit_scale
        laser_batches.append([int(j.end_vertex) for j in strokes])

    def carve_segments(segments, profile, tool_unit_scale=1.0, tool_def=None, volumes=None):
        del profile, tool_unit_scale, tool_def, volumes
        mill_batches.append([int(p1[0]) for _p0, p1, _a0, _a1 in segments])
        return set()

    backend.engrave_segments = engrave_segments
    backend.carve_segments = carve_segments
    return backend


def _laser_job(end_vertex: int) -> CarveJob:
    ev = int(end_vertex)
    return CarveJob(
        p0=(0.0, 0.0, 0.0),
        p1=(float(ev), 0.0, 0.0),
        tool_def=None,
        is_cut=True,
        end_vertex=ev,
        tool_number=LASER_TOOL_NUMBER,
    )


def _mill_job(end_vertex: int) -> CarveJob:
    ev = int(end_vertex)
    return CarveJob(
        p0=(0.0, 0.0, -1.0),
        p1=(float(ev), 0.0, -1.0),
        tool_def=_flat_tool(),
        is_cut=True,
        end_vertex=ev,
        tool_number=1,
    )


def _harness(path_vertex_count: int = 40, slot_count: int = 1):
    sim = StockSimulator()
    sim._generation = 1
    sim._resimulating = False
    sim._idle_cancel.clear()
    sim._checkpoints = CheckpointStore(slot_count=slot_count)
    sim._checkpoints.set_path_vertex_count(path_vertex_count)
    path = PathSnapshot([0.0, 0.0, 0.0], [2.0], [LASER_TOOL_NUMBER], {LASER_TOOL_NUMBER: None})

    laser_batches: list[list[int]] = []
    mill_batches: list[list[int]] = []

    backend = _mock_backend(laser_batches, mill_batches)

    def run(ends, *, idle: bool = True, tool_number: int = LASER_TOOL_NUMBER, to_vertex: int = 5):
        laser_batches.clear()
        mill_batches.clear()
        sim._idle_cancel.clear()

        def _iter(_path, _from_vertex, _to_vertex, *, voxel_size_mm, checkpoints):
            del _path, _from_vertex, _to_vertex, voxel_size_mm, checkpoints
            for end in ends:
                if callable(end):
                    end = end()
                if tool_number == LASER_TOOL_NUMBER:
                    yield _laser_job(end)
                else:
                    yield _mill_job(end)

        sim._iter_cut_jobs = _iter
        last, interrupted = sim._carve_segments_to(
            backend,
            path,
            1,
            0,
            to_vertex,
            set(),
            set(),
            idle=idle,
        )
        return last, interrupted, list(laser_batches), list(mill_batches)

    return sim, run


def test_idle_laser_batches_strokes_between_checkpoints():
    """Idle laser flushes multiple dashes in one engrave_segments call like foreground."""
    sim, run = _harness(path_vertex_count=40, slot_count=1)
    try:
        _last, interrupted, laser_batches, _mill = run((1, 2, 3, 4, 5), idle=True)
    finally:
        sim.stop()
    assert not interrupted
    assert laser_batches == [[1, 2, 3, 4, 5]]


def test_idle_laser_flushes_at_checkpoint_inside_run():
    sim, run = _harness(path_vertex_count=10, slot_count=4)
    assert sim._checkpoints.next_unrecorded_target() == 2
    try:
        _last, interrupted, laser_batches, _mill = run((1, 2, 3, 4, 5), idle=True, to_vertex=5)
    finally:
        sim.stop()
    assert not interrupted
    # CP at vertex 2, then at 4 (equal-spaced over 10 verts / 4 slots); each flushes
    # before deferring past the bookmark.
    assert laser_batches == [[1, 2], [3, 4], [5]]


def test_idle_cancel_flushes_queued_laser_once_then_stops():
    sim, run = _harness(path_vertex_count=40, slot_count=1)

    def ends():
        for end in (1, 2, 3, 4, 5, 6, 7, 8):
            if end == 6:
                sim._idle_cancel.set()
            yield end

    try:
        last, interrupted, laser_batches, _mill = run(ends(), idle=True)
    finally:
        sim.stop()
    assert interrupted
    assert last == 5
    assert laser_batches == [[1, 2, 3, 4, 5]]
    assert sim._bake_carved_vertex == 5


def test_idle_mill_still_flushes_one_segment_at_a_time():
    sim = StockSimulator()
    sim._generation = 1
    sim._resimulating = False
    sim._idle_cancel.clear()
    sim._checkpoints = CheckpointStore(slot_count=1)
    sim._checkpoints.set_path_vertex_count(40)
    path = PathSnapshot([0.0, 0.0, -1.0], [2.0], [1], {1: _flat_tool()})
    mill_batches: list[list[int]] = []
    backend = _mock_backend([], mill_batches)

    def _iter(_path, _from_vertex, _to_vertex, *, voxel_size_mm, checkpoints):
        del _path, _from_vertex, _to_vertex, voxel_size_mm, checkpoints
        for end in (1, 2, 3):
            yield _mill_job(end)

    sim._iter_cut_jobs = _iter
    try:
        last, interrupted = sim._carve_segments_to(
            backend,
            path,
            1,
            0,
            3,
            set(),
            set(),
            idle=True,
        )
    finally:
        sim.stop()
    assert not interrupted
    assert mill_batches == [[1], [2], [3]]
    assert last == 3
