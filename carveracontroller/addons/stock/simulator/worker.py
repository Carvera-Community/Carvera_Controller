"""Material-removal simulator driven by toolpath segments + tool profiles."""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Callable

from carveracontroller.addons.stock.simulator.carver_select import (
    BACKEND_CYLINDRICAL,
    BACKEND_HEIGHTMAP,
    BACKEND_VOXEL,
    DEFAULT_CARVER_MODE,
    normalize_carver_mode,
    recommend_carver,
)
from carveracontroller.addons.stock.simulator.carvers.laser_map import pick_laser_cell_size_mm
from carveracontroller.addons.stock.simulator.simulation_quality import (
    CHECKPOINT_SLOTS_BY_LEVEL,
    DEFAULT_CHECKPOINT_LEVEL,
    DEFAULT_VOXEL_RESOLUTION,
    pick_cell_size_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds, rotate_yz
from carveracontroller.addons.stock.stock_shape import RectangularStock, StockShape
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition
from carveracontroller.CNC import LASER_TOOL_NUMBER

logger = logging.getLogger(__name__)

# Sentinel to shut down the worker.
_STOP = object()
# Latest-wins poke: carve/rewind toward ``_display_vertex`` (no per-frame job flood).
_DISPLAY_FOLLOW = object()
# Emit pending dirty meshes immediately (pause catch-up).
_MESH_FLUSH = object()

# Throttle while the carved mesh is following playback (pause uses constructor default).
# Play matches pause: occupancy has headroom, so smaller patches track the tool.
DEFAULT_MESH_THROTTLE_S = 0.15
PLAY_MESH_THROTTLE_S = 0.15
# Playback remesh budget (flush / replace / pause / cylindrical shell ignore this).
MAX_MESH_TILES_PER_EMIT = 32

# Cut-segment merge knobs
_MERGE_TOL_VOXEL_FRAC = 0.25
_MERGE_MAX_MM_FLOOR = 8.0
_MERGE_MAX_MM_VOXEL_MULT = 16.0
_MERGE_MAX_SPAN = 64


def _chebyshev_tile(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _take_pending_mesh_keys(
    pending: set[tuple[int, int, int]],
    *,
    unlimited: bool,
    cap: int = MAX_MESH_TILES_PER_EMIT,
    around: tuple[int, int, int] | None = None,
) -> set[tuple[int, int, int]]:
    """Pop dirty keys to remesh. ``unlimited`` (flush / replace / pause / cylindrical) takes all.

    Capped play takes a connected blob around ``around`` (tool tile) so the live
    cut remeshes as one region instead of lexicographic slices that leave holes.
    """
    if unlimited or cap <= 0 or len(pending) <= cap:
        batch = set(pending)
        pending.clear()
        return batch
    if around is not None and around in pending:
        seed = around
    elif around is not None:
        seed = min(pending, key=lambda key: (_chebyshev_tile(key, around), key))
    else:
        seed = min(pending)
    batch: set[tuple[int, int, int]] = set()
    queued: set[tuple[int, int, int]] = {seed}
    q: deque[tuple[int, int, int]] = deque([seed])
    while q and len(batch) < cap:
        key = q.popleft()
        if key not in pending:
            continue
        batch.add(key)
        x, y, z = key
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    nbr = (x + dx, y + dy, z + dz)
                    if nbr in pending and nbr not in queued:
                        queued.add(nbr)
                        q.append(nbr)
    if len(batch) < cap:
        rest = sorted(pending - batch, key=lambda key: (_chebyshev_tile(key, seed), key))
        for key in rest:
            if len(batch) >= cap:
                break
            batch.add(key)
    pending.difference_update(batch)
    return batch


def _world_tile_key(backend, x: float, y: float, z: float) -> tuple[int, int, int] | None:
    """Occupancy tile/chunk containing world ``(x, y, z)``, or None."""
    kind = str(getattr(backend, "kind", ""))
    bounds = getattr(backend, "bounds", None)
    if bounds is None:
        return None
    if kind == BACKEND_HEIGHTMAP:
        ts = max(int(getattr(backend, "tile_size", 16)), 1)
        cell = float(getattr(backend, "cell_size", 1.0)) or 1.0
        tx = int(math.floor((float(x) - float(bounds.min_x)) / cell)) // ts
        ty = int(math.floor((float(y) - float(bounds.min_y)) / cell)) // ts
        return (tx, ty, 0)
    grid = getattr(backend, "grid", None)
    if grid is None:
        return None
    ix, iy, iz = grid.world_to_voxel(float(x), float(y), float(z))
    return grid.chunk_of_voxel(ix, iy, iz).as_tuple()


def _xyz_dist(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    dz = b[2] - a[2]
    return float((dx * dx + dy * dy + dz * dz) ** 0.5)


def _point_to_segment_dist_sq(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    p: tuple[float, float, float],
) -> float:
    """Squared distance from ``p`` to closed segment ``A→B``."""
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    abz = b[2] - a[2]
    apx = p[0] - a[0]
    apy = p[1] - a[1]
    apz = p[2] - a[2]
    ab_len_sq = abx * abx + aby * aby + abz * abz
    if ab_len_sq < 1e-18:
        return apx * apx + apy * apy + apz * apz
    t = (apx * abx + apy * aby + apz * abz) / ab_len_sq
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    dx = a[0] + t * abx - p[0]
    dy = a[1] + t * aby - p[1]
    dz = a[2] + t * abz - p[2]
    return dx * dx + dy * dy + dz * dz


def _merge_angle_tol_deg(
    p0: tuple[float, float, float],
    merge_tol_mm: float,
) -> float:
    """Degrees of A that match ``merge_tol_mm`` of arc at the tool's YZ radius."""
    r_ref = max(math.hypot(p0[1], p0[2]), 1.0)
    return math.degrees(max(float(merge_tol_mm), 0.0) / r_ref)


def _angle_error_on_xyz_chord(
    a: tuple[float, float, float],
    a_ang: float,
    p: tuple[float, float, float],
    p_ang: float,
    c: tuple[float, float, float],
    c_ang: float,
) -> float:
    """``|A(P) − lerp(A(A), A(C), t)|`` with ``t`` from the XYZ chord ``A→C``."""
    acx = c[0] - a[0]
    acy = c[1] - a[1]
    acz = c[2] - a[2]
    ac_len_sq = acx * acx + acy * acy + acz * acz
    if ac_len_sq < 1e-18:
        return abs(float(p_ang) - float(a_ang))
    t = ((p[0] - a[0]) * acx + (p[1] - a[1]) * acy + (p[2] - a[2]) * acz) / ac_len_sq
    expected = float(a_ang) + t * (float(c_ang) - float(a_ang))
    return abs(float(p_ang) - expected)


def _can_extend_collinear_merge(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    tol_mm: float,
) -> bool:
    """True if ``B`` lies within ``tol_mm`` of chord ``A→C`` (open projection).

    Local gate only; :func:`_clamp_collinear_run_end` enforces the final chord.
    """
    ab_len = _xyz_dist(a, b)
    if ab_len < 1e-12:
        return False
    acx = c[0] - a[0]
    acy = c[1] - a[1]
    acz = c[2] - a[2]
    ac_len_sq = acx * acx + acy * acy + acz * acz
    if ac_len_sq < 1e-18:
        return False
    bax = b[0] - a[0]
    bay = b[1] - a[1]
    baz = b[2] - a[2]
    t = (bax * acx + bay * acy + baz * acz) / ac_len_sq
    if t <= 0.0 or t >= 1.0:
        return False
    qx = a[0] + t * acx
    qy = a[1] + t * acy
    qz = a[2] + t * acz
    dx = b[0] - qx
    dy = b[1] - qy
    dz = b[2] - qz
    return (dx * dx + dy * dy + dz * dz) <= (tol_mm * tol_mm)


def _collinear_intermediates_within_tol(
    point_at: Callable[[int], tuple[float, float, float]],
    run_start: int,
    run_end: int,
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    tol_sq: float,
    *,
    angle_at: Callable[[int], float] | None = None,
    a0: float = 0.0,
    a1: float = 0.0,
    a_tol_deg: float = 0.0,
) -> bool:
    """True if every vertex in ``[run_start, run_end)`` lies within ``tol`` of chord ``p0→p1``."""
    for k in range(run_start, run_end):
        pk = point_at(k)
        if _point_to_segment_dist_sq(p0, p1, pk) > tol_sq:
            return False
        if angle_at is not None and a_tol_deg > 0.0:
            if _angle_error_on_xyz_chord(p0, a0, pk, angle_at(k), p1, a1) > a_tol_deg:
                return False
    return True


def _clamp_collinear_run_end(
    point_at: Callable[[int], tuple[float, float, float]],
    run_start: int,
    run_end: int,
    p0: tuple[float, float, float],
    tol_mm: float,
    *,
    angle_at: Callable[[int], float] | None = None,
    a0: float = 0.0,
    a_tol_deg: float = 0.0,
) -> tuple[int, tuple[float, float, float]]:
    """Longest prefix of ``[run_start, run_end]`` within ``tol_mm`` of the final chord."""
    if run_end <= run_start:
        return run_end, point_at(run_end)
    tol_sq = float(tol_mm) * float(tol_mm)

    def _ok(end: int) -> bool:
        p1 = point_at(end)
        a1 = float(angle_at(end)) if angle_at is not None else 0.0
        return _collinear_intermediates_within_tol(
            point_at,
            run_start,
            end,
            p0,
            p1,
            tol_sq,
            angle_at=angle_at,
            a0=a0,
            a1=a1,
            a_tol_deg=a_tol_deg,
        )

    p1 = point_at(run_end)
    if _ok(run_end):
        return run_end, p1

    best = run_start
    lo = run_start + 1
    hi = run_end - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if _ok(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best, point_at(best)


@dataclass(frozen=True)
class CarveJob:
    p0: tuple[float, float, float]
    p1: tuple[float, float, float]
    tool_def: ToolDefinition | None
    is_cut: bool
    end_vertex: int = 0  # path vertex at segment end (checkpoints / seek)
    a0: float = 0.0
    a1: float = 0.0
    tool_number: int | None = None
    spindle_s: float | None = None


@dataclass(frozen=True)
class CarveRangeJob:
    """Carve cut segments in ``(from_vertex, to_vertex]`` from the loaded toolpath."""

    from_vertex: int
    to_vertex: int
    # Idle ahead-carve: cancelled per-segment when real work is submitted.
    low_priority: bool = False


@dataclass(frozen=True)
class RecarveJob:
    """Restore nearest checkpoint ≤ target and carve the remainder on the worker."""

    target_vertex: int = 0


@dataclass(frozen=True)
class PathSnapshot:
    """Read-only toolpath refs for one worker job (copied under the lock)."""

    positions: list[float] | None
    vertex_types: list[float] | None
    tools: list[int] | None
    tool_table: dict | None
    tool_scale: float = 1.0
    angles: list[float] | None = None
    speeds: list[float] | None = None

    def vertex_count(self) -> int:
        if not self.positions:
            return 0
        return len(self.positions) // 3


MeshReadyCallback = Callable[[dict[tuple[int, int, int], tuple | None]], None]
ProgressCallback = Callable[[int], None]
CheckpointsCallback = Callable[[list[int]], None]


def _create_carver_backend(
    bounds: StockBounds,
    cell_size_mm: float,
    shape: StockShape,
    backend_kind: str,
    *,
    has_4axis: bool = False,
    resolution_level: str | None = None,
):
    """Instantiate the occupancy backend for ``backend_kind``."""
    del resolution_level
    cylindrical = backend_kind == BACKEND_CYLINDRICAL or (backend_kind == BACKEND_VOXEL and has_4axis)
    laser_cell = pick_laser_cell_size_mm(bounds, cell_size_mm, cylindrical=cylindrical)
    if backend_kind == BACKEND_HEIGHTMAP:
        from carveracontroller.addons.stock.simulator.carvers.heightmap import HeightmapBackend

        return HeightmapBackend(bounds, cell_size_mm, shape, laser_cell_size_mm=laser_cell)
    if backend_kind == BACKEND_CYLINDRICAL:
        from carveracontroller.addons.stock.simulator.carvers.cylindrical import CylindricalBackend

        return CylindricalBackend(bounds, cell_size_mm, shape, laser_cell_size_mm=laser_cell)
    from carveracontroller.addons.stock.simulator.carvers.voxel import VoxelBackend

    return VoxelBackend(
        bounds,
        cell_size_mm,
        shape,
        has_4axis=has_4axis,
        laser_cell_size_mm=laser_cell,
    )


class StockSimulator:
    """Background voxel carver synced to G-code playback.

    Carving / meshing / checkpoints run on a daemon thread. UI callers should
    only queue work (:meth:`set_toolpath`, :meth:`set_display_vertex`,
    :meth:`submit_range`, :meth:`submit_recarve_to`,
    :meth:`submit_idle_precompute`). Callbacks fire on the worker — hop to the
    Kivy clock before touching GL/widgets.

    Occupancy follows :meth:`set_display_vertex` (latest-wins) so the carved
    mesh can patch during play. Display-follow yields after the mesh throttle
    so remesh can run when the playhead stays ahead. Idle ahead-carve uses a
    second sparse bake grid so bookmarks can be recorded past the playhead
    without moving the displayed occupancy. It is skipped when
    :meth:`set_idle_ahead_allowed` is False.
    """

    def __init__(
        self,
        on_meshes_ready: MeshReadyCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_checkpoints: CheckpointsCallback | None = None,
        mesh_throttle_s: float = DEFAULT_MESH_THROTTLE_S,
    ):
        self._on_meshes_ready = on_meshes_ready
        self._on_progress = on_progress
        self._on_checkpoints = on_checkpoints
        self._mesh_throttle_s = mesh_throttle_s
        self._backend = None
        self._bake_backend = None
        self._carver_mode = DEFAULT_CARVER_MODE
        self._backend_kind = BACKEND_VOXEL
        self._cell_size_mm = 1.0
        self._bounds: StockBounds | None = None
        self._checkpoint_slots = CHECKPOINT_SLOTS_BY_LEVEL[DEFAULT_CHECKPOINT_LEVEL]
        self._resolution_level = DEFAULT_VOXEL_RESOLUTION
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.RLock()
        self._generation = 0
        self._resimulating = False
        self._enabled = False
        # Cancel in-flight idle without bumping generation (preserves CP jump).
        self._idle_cancel = threading.Event()
        self._checkpoints = None
        # Furthest carved vertex on the live / bake occupancy (worker-owned).
        self._grid_carved_vertex = 0
        self._bake_carved_vertex = 0
        # Latest-wins playhead the worker carves toward (UI-owned writes).
        self._display_vertex = 0
        self._display_poke_pending = False
        self._mesh_flush = False
        # Next mesh emit replaces all GPU chunks (after reset / recarve clear).
        self._force_mesh_replace = False
        # Packed cylindrical draw keys from the last emit (to tombstone extras).
        self._coalesce_gpu_keys: set[tuple[int, int, int]] = set()
        # Toolpath published from UI; worker copies refs per job under lock.
        self._path_positions: list[float] | None = None
        self._path_vertex_types: list[float] | None = None
        self._path_tools: list[int] | None = None
        self._path_angles: list[float] | None = None
        self._path_speeds: list[float] | None = None
        self._tool_table: dict | None = None
        self._tool_scale: float = 1.0
        self._has_4axis: bool = False
        self._has_off_axis_y: bool = False
        # When False, carve/checkpoint continue but mesh callbacks are skipped.
        self._mesh_updates_enabled = True
        # Viewer enables this only while paused so bake can fill checkpoints.
        self._idle_ahead_allowed = True
        # Placed solid used to seed non-box occupancy (default = full AABB).
        self._shape: StockShape = RectangularStock(width_mm=1.0, length_mm=1.0, height_mm=1.0)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def resimulating(self) -> bool:
        return self._resimulating

    @property
    def grid(self):
        """Voxel occupancy grid when the voxel carver is active, else ``None``."""
        with self._lock:
            backend = self._backend
            return getattr(backend, "grid", None) if backend is not None else None

    @property
    def carved_vertex(self) -> int:
        """Furthest vertex the live occupancy has been carved to (UI-thread safe)."""
        with self._lock:
            return int(self._grid_carved_vertex)

    @property
    def bake_grid(self):
        """Sparse occupancy used only to record ahead checkpoints (voxel grid or None)."""
        with self._lock:
            bake = self._bake_backend
            return getattr(bake, "grid", None) if bake is not None else None

    @property
    def bake_carved_vertex(self) -> int:
        """Furthest vertex the bake grid has been carved to (UI-thread safe)."""
        with self._lock:
            return int(self._bake_carved_vertex)

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @property
    def backend(self):
        """Active carver backend (voxel / heightmap / cylindrical)."""
        with self._lock:
            return self._backend

    @property
    def backend_kind(self) -> str:
        with self._lock:
            return str(self._backend_kind)

    def hud_stats(self) -> dict | None:
        """Viewer HUD snapshot, or ``None`` when simulation is off / has no grid."""
        with self._lock:
            if not self._enabled or self._backend is None:
                return None
            backend = self._backend
            store = self._active_checkpoint_store_locked()
            verts = store.vertices()
            head_vertex = max(verts) if verts else 0
            stats = dict(backend.hud_stats())
            stats.update(
                {
                    "checkpoint_count": len(store),
                    "checkpoint_max_count": int(store.target_count),
                    "checkpoint_head_vertex": int(head_vertex),
                    "resimulating": bool(self._resimulating),
                }
            )
            return stats

    def _active_checkpoint_store_locked(self):
        return self._checkpoints

    def _recommend_backend_kind_locked(self) -> str:
        """Resolve backend kind from mode + 4-axis flag + tools (caller holds lock)."""
        rec = recommend_carver(
            mode=self._carver_mode,
            has_4axis=self._has_4axis,
            has_off_axis_y=self._has_off_axis_y,
            tool_table=self._tool_table,
            tool_unit_scale=self._tool_scale,
        )
        return rec.backend

    def _install_backend_locked(self, bounds: StockBounds, shape: StockShape, cell_size: float, kind: str) -> None:
        """Create live backend. Caller holds lock."""
        backend = _create_carver_backend(
            bounds,
            cell_size,
            shape,
            kind,
            has_4axis=self._has_4axis,
            resolution_level=self._resolution_level,
        )
        self._backend = backend
        self._backend_kind = kind
        self._bake_backend = None
        n = 0 if self._path_positions is None else len(self._path_positions) // 3
        store = backend.create_checkpoint_store(self._checkpoint_slots)
        store.set_path_vertex_count(n)
        self._checkpoints = store

    def _restore_checkpoint_locked(self, backend, checkpoint) -> set[tuple[int, int, int]]:
        """Restore ``checkpoint`` onto ``backend`` via the backend's store helpers."""
        assert self._checkpoints is not None
        return type(backend).restore_checkpoint(self._checkpoints, checkpoint, backend)

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, name="StockSimulator", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._queue.put(_STOP)
        worker = self._worker
        if worker is None:
            return
        worker.join(timeout=2.0)
        if worker.is_alive():
            # Keep the handle so start()/reset() cannot spawn a second worker.
            logger.warning("StockSimulator worker did not stop within timeout")
            return
        if self._worker is worker:
            self._worker = None

    def reset(
        self,
        bounds: StockBounds,
        cell_size_mm: float | None = None,
        enable: bool = True,
        voxel_target: int | None = None,
        checkpoint_slots: int | None = None,
        shape: StockShape | None = None,
        carver_mode: str = DEFAULT_CARVER_MODE,
        resolution_level: str | None = None,
    ) -> None:
        """(Re)initialize the carver backend. Clears any pending carve jobs.

        ``voxel_target`` forces a cell count along the longest axis. Otherwise
        ``resolution_level`` (low/medium/high) picks a per-carver default target.
        """
        slots = (
            int(checkpoint_slots)
            if checkpoint_slots is not None
            else CHECKPOINT_SLOTS_BY_LEVEL[DEFAULT_CHECKPOINT_LEVEL]
        )
        with self._lock:
            self._generation += 1
            self._shape = (
                shape
                if shape is not None
                else RectangularStock(
                    width_mm=max(bounds.size[0], 1e-6),
                    length_mm=max(bounds.size[1], 1e-6),
                    height_mm=max(bounds.size[2], 1e-6),
                )
            )
            self._bounds = bounds
            self._carver_mode = normalize_carver_mode(carver_mode)
            self._checkpoint_slots = slots
            level = resolution_level if resolution_level is not None else DEFAULT_VOXEL_RESOLUTION
            self._resolution_level = level
            kind = self._recommend_backend_kind_locked()
            if cell_size_mm is not None:
                size = float(cell_size_mm)
            else:
                size = pick_cell_size_mm(
                    bounds,
                    carver=kind,
                    level=level,
                    target=voxel_target,
                )
            self._cell_size_mm = float(size)
            self._install_backend_locked(bounds, self._shape, size, kind)
            self._enabled = enable
            self._resimulating = False
            self._grid_carved_vertex = 0
            self._bake_carved_vertex = 0
            self._display_vertex = 0
            self._display_poke_pending = False
            self._mesh_flush = False
            self._force_mesh_replace = True
            self._mesh_updates_enabled = True
            self._coalesce_gpu_keys.clear()
        self._drain_queue()
        self.start()
        self._emit_checkpoints()
        if enable:
            self._emit_initial_surface()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._generation += 1
            self._backend = None
            self._bake_backend = None
            self._resimulating = False
            self._grid_carved_vertex = 0
            self._bake_carved_vertex = 0
            self._display_vertex = 0
            self._display_poke_pending = False
            self._mesh_flush = False
            self._force_mesh_replace = False
            self._mesh_updates_enabled = True
            self._coalesce_gpu_keys.clear()
            if self._checkpoints is not None:
                self._checkpoints.clear()
        self._drain_queue()
        if self._on_meshes_ready:
            self._on_meshes_ready({"__clear_all__": None})
        self._emit_progress(0)
        self._emit_checkpoints()

    def _emit_progress(self, vertex: int) -> None:
        if not self._on_progress:
            return
        try:
            self._on_progress(int(vertex))
        except Exception:
            logger.exception("stock progress callback failed")

    def _emit_checkpoints(self) -> None:
        if not self._on_checkpoints:
            return
        with self._lock:
            store = self._checkpoints
            vertices = store.vertices() if store is not None else []
        try:
            self._on_checkpoints(vertices)
        except Exception:
            logger.exception("stock checkpoints callback failed")

    def _maybe_record_checkpoint(
        self,
        vertex: int,
        backend,
        changed_keys: set[tuple[int, int, int]] | None = None,
    ) -> bool:
        if self._checkpoints is None:
            return False
        recorded = self._checkpoints.maybe_record(vertex, backend, changed_keys)
        if recorded:
            self._emit_checkpoints()
        return recorded

    def set_toolpath(
        self,
        positions: list[float] | None,
        vertex_types: list[float] | None,
        tools: list[int] | None,
        tool_table: dict | None,
        tool_scale: float = 1.0,
        angles: list[float] | None = None,
        has_4axis: bool = False,
        has_off_axis_y: bool = False,
        speeds: list[float] | None = None,
    ) -> None:
        """Publish the active toolpath (UI thread). Buffers must stay read-only.

        ``tool_scale`` is document-unit → mm (e.g. 25.4); applied after building
        the file-unit cutting profile, not passed into :func:`tool_profile`.
        ``has_4axis`` is the file-level A-axis flag (same as ``app.has_4axis``).
        ``has_off_axis_y`` is True when 4-axis feed moves leave Y=0 (index vs wrapping).
        """
        reinited = False
        with self._lock:
            self._path_positions = positions
            self._path_vertex_types = vertex_types
            self._path_tools = tools
            self._path_angles = angles
            self._path_speeds = speeds
            self._tool_table = tool_table
            self._tool_scale = float(tool_scale) if tool_scale else 1.0
            self._has_4axis = bool(has_4axis)
            self._has_off_axis_y = bool(has_off_axis_y)
            n = 0 if positions is None else len(positions) // 3
            if self._checkpoints is not None:
                self._checkpoints.set_path_vertex_count(n)
            # Auto mode may switch backend when the path arrives / changes.
            if (
                self._enabled
                and self._bounds is not None
                and self._backend is not None
                and normalize_carver_mode(self._carver_mode) == DEFAULT_CARVER_MODE
            ):
                kind = self._recommend_backend_kind_locked()
                if kind != self._backend_kind:
                    self._generation += 1
                    size = pick_cell_size_mm(
                        self._bounds,
                        carver=kind,
                        level=self._resolution_level,
                    )
                    self._cell_size_mm = float(size)
                    self._install_backend_locked(self._bounds, self._shape, size, kind)
                    self._grid_carved_vertex = 0
                    self._bake_carved_vertex = 0
                    self._force_mesh_replace = True
                    reinited = True
        self._emit_checkpoints()
        if reinited:
            self._drain_queue()
            self._emit_initial_surface()

    def clear_toolpath(self) -> None:
        self.set_toolpath(None, None, None, None, tool_scale=1.0)

    def set_display_vertex(self, vertex: int) -> None:
        """Latest-wins playhead: the worker carves or rewinds toward ``vertex``.

        Safe to call every frame. Coalesces to at most one queued poke.
        Preempts idle bake; the worker rearms it after catching up when idle
        ahead is allowed (paused).
        """
        if not self._enabled or self._backend is None:
            return
        v = max(0, int(vertex))
        with self._lock:
            if v == int(self._display_vertex) and v == int(self._grid_carved_vertex):
                return
            self._display_vertex = v
            already = self._display_poke_pending
            self._display_poke_pending = True
        self._idle_cancel.set()
        if not already:
            self._queue.put(_DISPLAY_FOLLOW)

    def set_mesh_throttle_s(self, seconds: float) -> None:
        """Change how long the worker batches dirty chunks before remeshing."""
        with self._lock:
            self._mesh_throttle_s = max(0.0, float(seconds))

    def request_mesh_flush(self) -> None:
        """Emit pending dirty meshes on the next worker wake (pause catch-up)."""
        if not self._enabled or self._backend is None:
            return
        with self._lock:
            self._mesh_flush = True
        self._queue.put(_MESH_FLUSH)

    def submit_range(self, from_vertex: int, to_vertex: int) -> None:
        """Queue carving for ``(from_vertex, to_vertex]`` (expanded on the worker)."""
        if not self._enabled or self._backend is None:
            return
        frm = max(0, int(from_vertex))
        to = max(0, int(to_vertex))
        if to <= frm:
            return
        self._idle_cancel.set()
        with self._lock:
            self._display_vertex = to
        self._queue.put(CarveRangeJob(from_vertex=frm, to_vertex=to))

    def submit_idle_precompute(self, from_vertex: int) -> None:
        """Queue low-priority bake-grid carving to record ahead checkpoints.

        Does not move the display grid. No-op when idle-ahead is disallowed.
        Pre-empted when any non-idle carve is submitted.
        """
        if not self._enabled or self._backend is None:
            return
        with self._lock:
            if not self._idle_ahead_allowed:
                return
            hint = max(0, int(from_vertex))
            to = self._path_vertex_count_locked() - 1
        if to <= 0:
            return
        self._idle_cancel.clear()
        self._queue.put(CarveRangeJob(from_vertex=hint, to_vertex=to, low_priority=True))

    def _maybe_rearm_idle_bake(self) -> None:
        """Resume bake after display follow preempted it (paused scrub)."""
        with self._lock:
            if not self._enabled or not self._idle_ahead_allowed or self._backend is None:
                return
            if int(self._display_vertex) != int(self._grid_carved_vertex):
                return
            hint = int(self._display_vertex)
        self.submit_idle_precompute(hint)

    def cancel_idle_precompute(self) -> None:
        """Stop in-flight idle precompute at the next segment boundary."""
        self._idle_cancel.set()

    def set_mesh_updates_enabled(self, enabled: bool) -> None:
        """Toggle mesh emits without stopping carve/checkpoint work.

        Dirty chunks are kept while suppressed. Re-enabling does not remesh;
        use :meth:`request_mesh_flush` for display.
        """
        with self._lock:
            self._mesh_updates_enabled = bool(enabled)

    def set_idle_ahead_allowed(self, allowed: bool) -> None:
        """Allow :meth:`submit_idle_precompute` (pause-only bake grid).

        The viewer enables this while paused and disables it while playing.
        """
        with self._lock:
            self._idle_ahead_allowed = bool(allowed)

    def submit_recarve_to(self, target_vertex: int = 0) -> None:
        """Seek-back / reload: restore checkpoint and carve up to ``target_vertex`` on the worker."""
        if not self._enabled or self._backend is None:
            return
        self._idle_cancel.set()
        with self._lock:
            self._generation += 1
            self._resimulating = True
            if self._backend is not None:
                self._backend.reset_occupancy()
            self._grid_carved_vertex = 0
            self._display_vertex = max(0, int(target_vertex))
            self._force_mesh_replace = True
        self._drain_queue()
        if self._on_meshes_ready:
            try:
                self._on_meshes_ready({"__clear_all__": None})
            except Exception:
                logger.exception("stock mesh clear callback failed")
        self._queue.put(RecarveJob(target_vertex=max(0, int(target_vertex))))

    def _emit_initial_surface(self) -> None:
        """Queue an empty recarve so the worker meshes the solid exterior shell."""
        if not self._enabled or self._backend is None:
            return
        with self._lock:
            self._resimulating = True
            self._force_mesh_replace = True
        self._queue.put(RecarveJob(target_vertex=0))

    def _prepare_bake_grid(self, gen: int, hint_vertex: int):
        """Create/restore the bake occupancy to the latest bookmark ≤ the bake head.

        Returns ``(bake_backend, start_vertex)``.
        """
        with self._lock:
            if self._generation != gen or not self._enabled or self._backend is None:
                return None
            if self._bake_backend is None:
                self._bake_backend = self._backend.clone_empty()
                self._bake_carved_vertex = 0
            bake = self._bake_backend
            bake_carved = int(self._bake_carved_vertex)
            hint = max(0, int(hint_vertex))
            target_head = max(bake_carved, hint)
            store = self._checkpoints
            cp = store.best_at_or_before(target_head) if store is not None else None
            if cp is not None:
                self._restore_checkpoint_locked(bake, cp)
                start = int(cp.vertex)
            else:
                bake.reset_occupancy()
                start = 0
            self._bake_carved_vertex = start
            return bake, start

    def _initial_surface_dirty_keys(self, backend=None) -> set[tuple[int, int, int]]:
        """Tiles that must remesh for an uncarved solid."""
        target = backend if backend is not None else self._backend
        if target is None:
            return set()
        return target.initial_surface_keys()

    def _path_snapshot_locked(self) -> PathSnapshot:
        """Copy path buffer refs under the lock (caller must hold ``_lock``)."""
        return PathSnapshot(
            positions=self._path_positions,
            vertex_types=self._path_vertex_types,
            tools=self._path_tools,
            tool_table=self._tool_table,
            tool_scale=self._tool_scale,
            angles=self._path_angles,
            speeds=self._path_speeds,
        )

    def _path_vertex_count_locked(self) -> int:
        """Path length under the lock (caller must hold ``_lock``)."""
        positions = self._path_positions
        if not positions:
            return 0
        return len(positions) // 3

    def _restore_checkpoint_at_or_before(
        self,
        backend,
        vertex: int,
    ) -> tuple[int, set[tuple[int, int, int]]]:
        """Restore nearest checkpoint ≤ ``vertex``. Caller must hold ``_lock``.

        Returns ``(start_vertex, restored_keys)``. Resets to solid if none.
        """
        store = self._checkpoints
        cp = store.best_at_or_before(vertex) if store is not None else None
        if cp is None:
            dirty = backend.reset_occupancy()
            return 0, dirty
        dirty = self._restore_checkpoint_locked(backend, cp)
        return int(cp.vertex), dirty

    @staticmethod
    def _is_cut_vertex(path: PathSnapshot, idx: int) -> bool:
        types = path.vertex_types
        if not types or idx < 0 or idx >= len(types):
            return False
        return float(types[idx]) <= 1.5

    @staticmethod
    def _tool_number_at_vertex(path: PathSnapshot, idx: int) -> int | None:
        tools = path.tools
        if not tools or idx < 0 or idx >= len(tools):
            return None
        return int(tools[idx])

    @staticmethod
    def _tool_def_at_vertex(path: PathSnapshot, idx: int) -> ToolDefinition | None:
        tools = path.tools
        table = path.tool_table
        if not tools or not table or idx < 0 or idx >= len(tools):
            return None
        return table.get(int(tools[idx]))

    @staticmethod
    def _raw_xyz(path: PathSnapshot, idx: int) -> tuple[float, float, float]:
        pos = path.positions
        base = idx * 3
        return (float(pos[base]), float(pos[base + 1]), float(pos[base + 2]))

    @staticmethod
    def _raw_angle(path: PathSnapshot, idx: int) -> float:
        angs = path.angles
        if not angs or idx < 0 or idx >= len(angs):
            return 0.0
        return float(angs[idx])

    def _mesh_focus_key(self, backend, path: PathSnapshot | None, vertex: int) -> tuple[int, int, int] | None:
        """Tile under the playhead, used to prefer live-cut remesh over leftover tiles."""
        if backend is None or path is None or not path.positions:
            return None
        n = path.vertex_count()
        if n <= 0:
            return None
        idx = max(0, min(int(vertex), n - 1))
        x, y, z = self._raw_xyz(path, idx)
        ang = self._raw_angle(path, idx)
        if abs(ang) > 1e-9:
            y, z = rotate_yz(y, z, ang)
        return _world_tile_key(backend, x, y, z)

    def _carve_job(
        self,
        path: PathSnapshot,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def: ToolDefinition | None,
        start_idx: int,
        end_idx: int,
    ) -> CarveJob:
        return CarveJob(
            p0=p0,
            p1=p1,
            tool_def=tool_def,
            is_cut=True,
            end_vertex=end_idx,
            a0=self._raw_angle(path, start_idx),
            a1=self._raw_angle(path, end_idx),
            tool_number=self._tool_number_at_vertex(path, end_idx),
            spindle_s=self._spindle_at_vertex(path, end_idx),
        )

    @staticmethod
    def _spindle_at_vertex(path: PathSnapshot, idx: int) -> float | None:
        speeds = path.speeds
        if not speeds or idx < 0 or idx >= len(speeds):
            return None
        return float(speeds[idx])

    def _iter_cut_jobs(
        self,
        path: PathSnapshot,
        from_vertex: int,
        to_vertex: int,
        *,
        voxel_size_mm: float,
        checkpoints,
    ) -> Iterator[CarveJob]:
        """Yield merged cut jobs with ``end_vertex`` in ``(from_vertex, to_vertex]``.

        Near-collinear same-tool cuts collapse to a chord, flushing at the next
        unrecorded checkpoint target or length/span caps. After greedy extend,
        :func:`_clamp_collinear_run_end` keeps intermediates within tolerance.
        Rotary moves must also keep A on that XYZ chord so wrapping Z-profiles
        are not flattened into a machine-XYZ line.
        """
        n = path.vertex_count()
        if n < 2:
            return
        # Segment ending at i connects vertices i-1 → i.
        start = max(1, int(from_vertex) + 1)
        end = min(n - 1, int(to_vertex))
        merge_tol = _MERGE_TOL_VOXEL_FRAC * float(voxel_size_mm)
        max_merge_mm = max(_MERGE_MAX_MM_FLOOR, _MERGE_MAX_MM_VOXEL_MULT * float(voxel_size_mm))
        max_span = _MERGE_MAX_SPAN

        def point_at(idx: int) -> tuple[float, float, float]:
            return self._raw_xyz(path, idx)

        def angle_at(idx: int) -> float:
            return self._raw_angle(path, idx)

        i = start
        while i <= end:
            if not self._is_cut_vertex(path, i):
                i += 1
                continue

            run_end = i
            p0 = self._raw_xyz(path, i - 1)
            p1 = self._raw_xyz(path, run_end)
            a0 = self._raw_angle(path, i - 1)
            a_tol = _merge_angle_tol_deg(p0, merge_tol)
            tool_num = self._tool_number_at_vertex(path, run_end)
            tool_def = self._tool_def_at_vertex(path, run_end)
            path_len = _xyz_dist(p0, p1)
            span = 1
            # Re-peek so interleaved maybe_record advances are visible.
            break_at = checkpoints.next_unrecorded_target()
            # Target already behind this segment: flush one job so recording can catch up.
            if break_at is not None and i > break_at:
                yield self._carve_job(path, p0, p1, tool_def, i - 1, run_end)
                i = run_end + 1
                continue

            # Don't merge laser strokes: short raster G1s become lead-in chords.
            if tool_num == LASER_TOOL_NUMBER:
                yield self._carve_job(path, p0, p1, tool_def, i - 1, run_end)
                i = run_end + 1
                continue

            j = i + 1
            while j <= end:
                if not self._is_cut_vertex(path, j):
                    break
                if self._tool_number_at_vertex(path, j) != tool_num:
                    break
                if break_at is not None and j > break_at:
                    break

                p_new = self._raw_xyz(path, j)
                step = _xyz_dist(p1, p_new)
                a_only = _xyz_dist(p0, p_new) <= merge_tol and step <= merge_tol
                if not a_only:
                    if not _can_extend_collinear_merge(p0, p1, p_new, merge_tol):
                        break
                    # XYZ-collinear wrapping (constant X/Y, Z follows the surface)
                    # is a straight line in machine XYZ; A must follow that chord
                    # or a 4-axis bump collapses into an overcutting ramp.
                    a_end = self._raw_angle(path, run_end)
                    a_new = self._raw_angle(path, j)
                    if _angle_error_on_xyz_chord(p0, a0, p1, a_end, p_new, a_new) > a_tol:
                        break

                if (not a_only) and (path_len + step > max_merge_mm or span + 1 > max_span):
                    break
                if a_only and span + 1 > max_span:
                    break

                p1 = p_new
                run_end = j
                path_len += step
                span += 1
                j += 1

                if break_at is not None and run_end >= break_at:
                    break

            if run_end > i and not (_xyz_dist(p0, p1) <= merge_tol):
                run_end, p1 = _clamp_collinear_run_end(
                    point_at,
                    i,
                    run_end,
                    p0,
                    merge_tol,
                    angle_at=angle_at,
                    a0=a0,
                    a_tol_deg=a_tol,
                )

            yield self._carve_job(path, p0, p1, tool_def, i - 1, run_end)
            i = run_end + 1

    def _rewind_grid_to(
        self,
        backend,
        gen: int,
        vertex: int,
    ) -> tuple[int, set[tuple[int, int, int]]] | None:
        """Restore occupancy to a checkpoint ≤ ``vertex``. Returns ``(start, dirty)``."""
        with self._lock:
            if self._generation != gen:
                return None
            if backend is not self._backend:
                return None
            old_keys = backend.all_non_full_keys()
            start_vertex, restored_keys = self._restore_checkpoint_at_or_before(backend, vertex)
            self._grid_carved_vertex = start_vertex
            return start_vertex, old_keys | restored_keys

    def _maybe_jump_checkpoint(
        self,
        backend,
        gen: int,
        start_vertex: int,
        to_vertex: int,
    ) -> tuple[int, set[tuple[int, int, int]]]:
        """If a checkpoint sits between ``start_vertex`` and ``to_vertex``, restore it."""
        with self._lock:
            if self._generation != gen:
                return start_vertex, set()
            if backend is not self._backend:
                return start_vertex, set()
            store = self._checkpoints
            cp = store.best_at_or_before(to_vertex) if store is not None else None
            if cp is None or cp.vertex <= start_vertex:
                return start_vertex, set()
            old_keys = backend.all_non_full_keys()
            restored_keys = self._restore_checkpoint_locked(backend, cp)
            self._grid_carved_vertex = cp.vertex
            return cp.vertex, old_keys | restored_keys

    def _carve_segments_to(
        self,
        grid_or_backend,
        path: PathSnapshot,
        gen: int,
        start_vertex: int,
        to_vertex: int,
        pending_dirty: set[tuple[int, int, int]],
        changed_since_cp: set[tuple[int, int, int]],
        *,
        idle: bool = False,
        follow_display: bool = False,
        deadline: float | None = None,
    ) -> tuple[int, bool]:
        """Carve ``(start_vertex, to_vertex]``. Returns ``(last_end, interrupted)``.

        ``deadline`` (monotonic) stops a display-follow pass so the worker can remesh.
        """
        last_end_vertex = start_vertex
        interrupted = False
        last_progress_t = 0.0
        cell = float(getattr(grid_or_backend, "cell_size", self._cell_size_mm))
        store = self._checkpoints
        if store is None:
            return last_end_vertex, True
        for seg in self._iter_cut_jobs(
            path,
            start_vertex,
            to_vertex,
            voxel_size_mm=cell,
            checkpoints=store,
        ):
            if self._generation != gen or self._resimulating:
                interrupted = True
                break
            if idle and self._idle_cancel.is_set():
                interrupted = True
                break
            if follow_display:
                with self._lock:
                    live_target = int(self._display_vertex)
                if live_target < seg.end_vertex:
                    interrupted = True
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    interrupted = True
                    break
            # Carve outside the lock so HUD/playhead can progress during long wraps.
            dirty = self._carve_one(grid_or_backend, seg, path.tool_scale)
            with self._lock:
                if self._generation != gen or self._resimulating:
                    interrupted = True
                    break
                pending_dirty.update(dirty)
                changed_since_cp.update(dirty)
                if self._maybe_record_checkpoint(seg.end_vertex, grid_or_backend, changed_since_cp):
                    changed_since_cp.clear()
                if idle:
                    self._bake_carved_vertex = seg.end_vertex
                else:
                    self._grid_carved_vertex = seg.end_vertex
            last_end_vertex = seg.end_vertex
            if not idle:
                now_p = time.monotonic()
                if now_p - last_progress_t >= 0.05:
                    self._emit_progress(seg.end_vertex)
                    last_progress_t = now_p
        if not interrupted:
            with self._lock:
                if self._generation != gen or self._resimulating:
                    return last_end_vertex, True
                filled = True
                while True:
                    nxt = store.next_unrecorded_target()
                    if nxt is None or int(nxt) > int(to_vertex):
                        break
                    if not self._maybe_record_checkpoint(int(nxt), grid_or_backend, changed_since_cp):
                        filled = False
                        break
                    changed_since_cp.clear()
                    last_end_vertex = int(nxt)
                if filled:
                    last_end_vertex = max(last_end_vertex, int(to_vertex))
                    if idle:
                        self._bake_carved_vertex = last_end_vertex
                    else:
                        self._grid_carved_vertex = last_end_vertex
        return last_end_vertex, interrupted

    def _follow_display_vertex(
        self,
        grid_or_backend,
        path: PathSnapshot,
        gen: int,
        pending_dirty: set[tuple[int, int, int]],
        changed_since_cp: set[tuple[int, int, int]],
    ) -> None:
        """Carve or rewind the live occupancy toward ``_display_vertex``.

        While playing, yields after ``_mesh_throttle_s`` so remesh can run even if
        still behind. Pause/scrub (idle-ahead allowed) and mesh-off carve until
        caught up so the displayed stock can remesh in one shot.
        """
        with self._lock:
            budget = max(float(self._mesh_throttle_s), 0.0)
            mesh_updates = bool(self._mesh_updates_enabled)
            playing = not bool(self._idle_ahead_allowed)
        deadline = None if (budget <= 0.0 or not mesh_updates or not playing) else time.monotonic() + budget
        while self._generation == gen and not self._resimulating:
            if deadline is not None and time.monotonic() >= deadline:
                return
            with self._lock:
                if self._generation != gen:
                    return
                if grid_or_backend is not self._backend:
                    return
                target = int(self._display_vertex)
                carved = int(self._grid_carved_vertex)
            if target == carved:
                return
            start_vertex = carved
            if target < carved:
                rewound = self._rewind_grid_to(grid_or_backend, gen, target)
                if rewound is None:
                    return
                start_vertex, dirty = rewound
                pending_dirty.update(dirty)
                changed_since_cp.clear()
                self._emit_progress(start_vertex)
                if target <= start_vertex:
                    with self._lock:
                        if self._generation == gen:
                            self._grid_carved_vertex = int(target)
                    self._emit_progress(target)
                    return
            start_vertex, jump_dirty = self._maybe_jump_checkpoint(grid_or_backend, gen, start_vertex, target)
            if jump_dirty:
                pending_dirty.update(jump_dirty)
                changed_since_cp.clear()
                self._emit_progress(start_vertex)
            _last_end, interrupted = self._carve_segments_to(
                grid_or_backend,
                path,
                gen,
                start_vertex,
                target,
                pending_dirty,
                changed_since_cp,
                follow_display=True,
                deadline=deadline,
            )
            if self._generation != gen:
                return
            with self._lock:
                live_target = int(self._display_vertex)
                if not interrupted:
                    self._grid_carved_vertex = int(target)
            if not interrupted:
                self._emit_progress(target)
            if live_target == target and not interrupted:
                return
            if deadline is not None and time.monotonic() >= deadline:
                return
            # Target moved (ahead or behind) or a mid-carve interrupt: loop.

    def _worker_loop(self) -> None:
        pending_dirty: set[tuple[int, int, int]] = set()
        # Chunks carved since the last recorded checkpoint (delta candidates).
        display_changed_since_cp: set[tuple[int, int, int]] = set()
        bake_changed_since_cp: set[tuple[int, int, int]] = set()
        dirty_gen = self._generation
        last_emit = 0.0

        while True:
            with self._lock:
                throttle = self._mesh_throttle_s
            try:
                item = self._queue.get(timeout=throttle)
            except queue.Empty:
                item = None

            if item is _STOP:
                break

            with self._lock:
                gen = self._generation
                backend = self._backend
                enabled = self._enabled
                resimulating = self._resimulating
                path = self._path_snapshot_locked()
                display_vertex = int(self._display_vertex)
                carved_vertex = int(self._grid_carved_vertex)
                do_flush = self._mesh_flush
                force_replace = self._force_mesh_replace
                mesh_updates = self._mesh_updates_enabled

            if gen != dirty_gen:
                pending_dirty.clear()
                display_changed_since_cp.clear()
                bake_changed_since_cp.clear()
                self._coalesce_gpu_keys.clear()
                dirty_gen = gen

            live = backend
            if live is None or not enabled:
                pending_dirty.clear()
                display_changed_since_cp.clear()
                bake_changed_since_cp.clear()
                continue

            # During seek/reset, only RecarveJob may mutate the display grid.
            if resimulating and not isinstance(item, RecarveJob):
                pending_dirty.clear()
                display_changed_since_cp.clear()
                continue

            finished_recarve = False
            recarve_finished = False
            did_display_follow = False
            if item is _DISPLAY_FOLLOW:
                with self._lock:
                    self._display_poke_pending = False
                self._follow_display_vertex(live, path, gen, pending_dirty, display_changed_since_cp)
                did_display_follow = True

            elif item is _MESH_FLUSH:
                pass

            elif item is None and mesh_updates and display_vertex != carved_vertex:
                self._follow_display_vertex(live, path, gen, pending_dirty, display_changed_since_cp)
                did_display_follow = True

            elif isinstance(item, RecarveJob):
                with self._lock:
                    if self._generation != gen:
                        continue
                    if live is not self._backend:
                        continue
                    self._resimulating = True
                    start_vertex, restored_keys = self._restore_checkpoint_at_or_before(live, item.target_vertex)
                    self._grid_carved_vertex = start_vertex
                pending_dirty.clear()
                pending_dirty.update(restored_keys)
                display_changed_since_cp.clear()
                dirty_gen = gen
                self._emit_progress(start_vertex)
                last_end, _interrupted = self._carve_segments_to(
                    live,
                    path,
                    gen,
                    start_vertex,
                    item.target_vertex,
                    pending_dirty,
                    display_changed_since_cp,
                )
                if self._generation == gen:
                    final_vertex = int(item.target_vertex if item.target_vertex else last_end)
                    self._emit_progress(final_vertex)
                    with self._lock:
                        self._grid_carved_vertex = final_vertex
                    # Remesh the stock shell so __replace__ does not leave uncarved voids.
                    pending_dirty.update(self._initial_surface_dirty_keys(live))
                with self._lock:
                    if self._generation == gen:
                        finished_recarve = True
                        recarve_finished = True
                    else:
                        pending_dirty.clear()
                        continue
                last_emit = 0.0

            elif isinstance(item, CarveRangeJob) and item.low_priority:
                if self._generation != gen or self._resimulating:
                    continue
                # Idle bake ``continue``s past the shared remesh step. Flush any
                # leftover display-dirty tiles first or paused scrub stays stale.
                if mesh_updates and (pending_dirty or bool(getattr(live, "_laser_dirty", False))):
                    batch = _take_pending_mesh_keys(pending_dirty, unlimited=True)
                    if self._try_mesh_and_emit(live, batch, gen, replace=False):
                        last_emit = time.monotonic()
                    else:
                        pending_dirty.update(batch)
                if self._idle_cancel.is_set():
                    continue
                prepared = self._prepare_bake_grid(gen, item.from_vertex)
                if prepared is None:
                    continue
                bake, start_vertex = prepared
                bake_changed_since_cp.clear()
                if start_vertex >= item.to_vertex:
                    continue
                bake_dirty: set[tuple[int, int, int]] = set()
                self._carve_segments_to(
                    bake,
                    path,
                    gen,
                    start_vertex,
                    item.to_vertex,
                    bake_dirty,
                    bake_changed_since_cp,
                    idle=True,
                )
                continue

            elif isinstance(item, CarveRangeJob):
                if self._generation != gen or self._resimulating:
                    pending_dirty.clear()
                    display_changed_since_cp.clear()
                    continue

                start_vertex = item.from_vertex

                if self._grid_carved_vertex > item.from_vertex:
                    rewound = self._rewind_grid_to(live, gen, item.from_vertex)
                    if rewound is None:
                        continue
                    start_vertex, dirty_keys = rewound
                    pending_dirty.update(dirty_keys)
                    display_changed_since_cp.clear()
                    dirty_gen = gen

                start_vertex, jump_dirty = self._maybe_jump_checkpoint(live, gen, start_vertex, item.to_vertex)
                if jump_dirty:
                    pending_dirty.update(jump_dirty)
                    display_changed_since_cp.clear()
                    dirty_gen = gen

                last_end_vertex, interrupted = self._carve_segments_to(
                    live,
                    path,
                    gen,
                    start_vertex,
                    item.to_vertex,
                    pending_dirty,
                    display_changed_since_cp,
                )

                if self._generation == gen:
                    final_vertex = last_end_vertex if interrupted else item.to_vertex
                    self._emit_progress(final_vertex)
                    with self._lock:
                        self._grid_carved_vertex = int(final_vertex)

            now = time.monotonic()
            with self._lock:
                mesh_updates = self._mesh_updates_enabled
                do_flush = self._mesh_flush
                force_replace = self._force_mesh_replace
                throttle = self._mesh_throttle_s
                idle_ahead = bool(self._idle_ahead_allowed)
                caught_up = int(self._display_vertex) == int(self._grid_carved_vertex)
                focus_vertex = int(self._display_vertex)
            replace = finished_recarve or force_replace
            laser_pending = bool(getattr(live, "_laser_dirty", False))
            coalesce = str(getattr(live, "kind", "")) == BACKEND_CYLINDRICAL
            # Pause/scrub must remesh as soon as follow returns: idle bake is
            # queued next and would skip this emit via ``continue``.
            pause_follow_emit = idle_ahead and did_display_follow
            should_emit = (
                replace
                or do_flush
                or ((pending_dirty or laser_pending) and (pause_follow_emit or (now - last_emit) >= throttle))
            )
            if should_emit:
                if not mesh_updates:
                    # Keep dirty so pause can flush visited chunks without a
                    # full-shell replace. Consume flush to avoid a busy loop.
                    last_emit = now
                    with self._lock:
                        self._mesh_flush = False
                else:
                    unlimited = replace or do_flush or coalesce or idle_ahead
                    focus = self._mesh_focus_key(live, path, focus_vertex)
                    drain_until = time.monotonic() + max(float(throttle), 0.0)
                    while True:
                        batch = _take_pending_mesh_keys(
                            pending_dirty,
                            unlimited=unlimited,
                            cap=MAX_MESH_TILES_PER_EMIT,
                            around=focus,
                        )
                        halo: set[tuple[int, int, int]] = set()
                        if batch and not unlimited:
                            # expand_dirty remeshes neighbours (pocket walls / floor).
                            # Drop them from pending so leftover drain is only tiles
                            # this emit did not cover.
                            halo = set(live.expand_dirty(batch))
                            pending_dirty.difference_update(halo)
                        if self._try_mesh_and_emit(live, batch, gen, replace=replace, force_emit=do_flush):
                            last_emit = time.monotonic()
                            with self._lock:
                                if replace:
                                    self._force_mesh_replace = False
                                self._mesh_flush = False
                        else:
                            pending_dirty.update(batch)
                            pending_dirty.update(halo)
                            break
                        if unlimited or not pending_dirty:
                            break
                        if not batch and not do_flush:
                            break
                        # Play leftover: keep remeshing while occupancy matches the
                        # playhead (rapids/dwell). One batch per window while behind.
                        if not caught_up or idle_ahead or time.monotonic() >= drain_until:
                            break
                        replace = False
                        do_flush = False
                        unlimited = False
            if recarve_finished:
                with self._lock:
                    if self._generation == gen:
                        self._resimulating = False
                with self._lock:
                    poke_display = self._display_poke_pending
                if poke_display:
                    self._queue.put(_DISPLAY_FOLLOW)

            if did_display_follow:
                with self._lock:
                    still_behind = int(self._display_vertex) != int(self._grid_carved_vertex)
                    already = self._display_poke_pending
                    if still_behind and not already:
                        self._display_poke_pending = True
                if still_behind and not already:
                    self._queue.put(_DISPLAY_FOLLOW)
                elif not still_behind and not pending_dirty:
                    self._maybe_rearm_idle_bake()

        if pending_dirty or bool(getattr(self._backend, "_laser_dirty", False)):
            with self._lock:
                live = self._backend
                gen = self._generation
                enabled = self._enabled
                mesh_updates = self._mesh_updates_enabled
            if enabled and live is not None and mesh_updates:
                self._try_mesh_and_emit(live, pending_dirty, gen, replace=False)
            pending_dirty.clear()

    def _try_mesh_and_emit(
        self,
        backend,
        dirty: set[tuple[int, int, int]],
        gen: int,
        *,
        replace: bool,
        force_emit: bool = False,
    ) -> bool:
        """Copy mesh-relevant tiles under lock, mesh unlocked, emit if still current.

        Generation is stamped under lock to match the emitted meshes.
        ``force_emit`` (pause flush) notifies even when nothing is dirty so the
        viewer can swap AABB fill for carved stock.
        """
        if not self._on_meshes_ready:
            return True

        with self._lock:
            if self._generation != gen or not self._enabled or self._backend is None:
                return False
            if backend is not self._backend:
                return False
            dirty_keys = set(dirty)
            # Cylindrical wraps in θ and is drawn as one field. Playback patches
            # that field in place (no __replace__) so the viewer does not
            # destroy GPU meshes every throttle window. Heightmap/voxel tiles
            # patch incrementally.
            coalesce = str(getattr(backend, "kind", "")) == BACKEND_CYLINDRICAL
            if dirty_keys:
                if coalesce:
                    mesh_keys = backend.initial_surface_keys()
                    tmp = backend.copy_tiles(mesh_keys)
                else:
                    mesh_keys = backend.expand_dirty(dirty_keys)
                    copy_keys = backend.expand_dirty(mesh_keys)
                    tmp = backend.copy_tiles(copy_keys)
            else:
                mesh_keys = set()
                tmp = None

        if dirty_keys and tmp is not None:
            meshes = tmp.mesh_tiles(mesh_keys)
        else:
            meshes = {}

        with self._lock:
            if self._generation != gen or self._backend is None:
                return False
            include_laser = False
            laser_payload = None
            take = getattr(backend, "take_laser_dirty", None)
            get = getattr(backend, "laser_gpu_payload", None)
            if take is not None and take():
                include_laser = True
                laser_payload = get() if get is not None else None
            elif replace and get is not None:
                include_laser = True
                laser_payload = get()
            try:
                if coalesce and meshes:
                    current = {k for k, packed in meshes.items() if packed is not None}
                    if not replace:
                        for old in self._coalesce_gpu_keys - current:
                            meshes[old] = None
                    self._coalesce_gpu_keys = current
                out: dict = {}
                if replace:
                    if dirty_keys or meshes:
                        out["__replace__"] = meshes
                    if include_laser:
                        out["__laser__"] = laser_payload
                    if out or force_emit:
                        self._on_meshes_ready(out)
                    return True
                out = dict(meshes)
                if include_laser:
                    out["__laser__"] = laser_payload
                if out or force_emit:
                    self._on_meshes_ready(out)
            except Exception:
                logger.exception("stock mesh callback failed")
            return True

    def _carve_one(
        self,
        backend,
        job: CarveJob,
        tool_unit_scale: float = 1.0,
    ) -> set[tuple[int, int, int]]:
        if not job.is_cut:
            return set()
        kwargs = {}
        if abs(float(job.a0)) > 1e-9 or abs(float(job.a1)) > 1e-9:
            kwargs["a0"] = job.a0
            kwargs["a1"] = job.a1
        if job.tool_number == LASER_TOOL_NUMBER:
            dx = float(job.p1[0]) - float(job.p0[0])
            dy = float(job.p1[1]) - float(job.p0[1])
            dz = float(job.p1[2]) - float(job.p0[2])
            da = abs(float(job.a1) - float(job.a0))
            # Skip Z-only plunges; keep XY/A strokes and point stamps.
            if (dx * dx + dy * dy) < 1e-8 and abs(dz) > 0.02 and da < 0.5:
                return set()
            engrave = getattr(backend, "engrave_segment", None)
            if engrave is not None:
                engrave(
                    job.p0,
                    job.p1,
                    job.tool_def,
                    tool_unit_scale=tool_unit_scale,
                    power_s=job.spindle_s,
                    **kwargs,
                )
            return set()
        return backend.carve_segment(
            job.p0,
            job.p1,
            job.tool_def,
            tool_unit_scale=tool_unit_scale,
            **kwargs,
        )
