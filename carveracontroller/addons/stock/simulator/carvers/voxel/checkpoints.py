"""Bit-packed voxel occupancy checkpoints."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.laser_map import laser_snapshot_nbytes

from .grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord, ChunkedVoxelGrid

# Packed-checkpoint sentinels (compare with ``is``). ``_REMOVED`` = back to FULL.
_PACKED_EMPTY = "EMPTY"
_REMOVED = "REMOVED"


def _pack_chunk_state(state: object) -> object:
    """Bit-pack a chunk's occupancy array (8x smaller than the uint8 grid)."""
    if state is CHUNK_EMPTY:
        return _PACKED_EMPTY
    return np.packbits(np.ascontiguousarray(state).reshape(-1))


def _unpack_chunk_state(packed: object, chunk_size: int) -> object:
    if packed is _PACKED_EMPTY:
        return CHUNK_EMPTY
    n = chunk_size * chunk_size * chunk_size
    arr = np.unpackbits(packed, count=n)
    return arr.reshape(chunk_size, chunk_size, chunk_size).astype(np.uint8)


def _packed_nbytes(value: object) -> int:
    if value is _PACKED_EMPTY or value is _REMOVED:
        return 16  # small fixed overhead for the sentinel + dict key
    return int(value.nbytes)


def _packed_equal(a: object, b: object) -> bool:
    if a is _PACKED_EMPTY or b is _PACKED_EMPTY:
        return a is b
    return bool(a.shape == b.shape and np.array_equal(a, b))


@dataclass(frozen=True)
class GridCheckpoint:
    vertex: int
    # Base: all non-FULL chunks. Delta: changed since previous CP in the GOP
    # (packed array, ``_PACKED_EMPTY``, or ``_REMOVED``).
    is_base: bool
    data: dict[tuple[int, int, int], object]
    nbytes: int
    laser: object | None = None


def _equal_spaced_targets(path_vertex_count: int, slot_count: int) -> list[int]:
    """Unique sorted vertex indices evenly spaced over ``(0, V-1]``."""
    v = int(path_vertex_count)
    n = max(1, int(slot_count))
    if v < 2:
        return []
    last = v - 1
    return list(dict.fromkeys(t for t in (int(round(i * last / n)) for i in range(1, n + 1)) if t > 0))


class CheckpointStore:
    """Sparse bit-packed grid snapshots at equal-spaced toolpath targets.

    Most entries are deltas since the previous checkpoint; every
    ``base_interval``-th is a full base so seeks replay at most one GOP.
    """

    def __init__(self, slot_count: int = 1024, base_interval: int = 4):
        self.slot_count = max(1, int(slot_count))
        self.base_interval = max(1, int(base_interval))
        self._path_vertex_count = 0
        self._targets: list[int] = []
        self._next_target_idx = 0
        self._items: list[GridCheckpoint] = []
        # Incremental packed non-FULL map as of the last recorded checkpoint.
        self._last_full_map: dict[tuple[int, int, int], object] = {}

    def clear(self) -> None:
        self._items.clear()
        self._last_full_map = {}
        self._next_target_idx = 0

    def set_path_vertex_count(self, n: int) -> None:
        """Recompute targets for ``n`` vertices; no-op when ``n`` is unchanged."""
        n = max(0, int(n))
        if n == self._path_vertex_count:
            return
        self._path_vertex_count = n
        self._targets = _equal_spaced_targets(n, self.slot_count)
        self.clear()

    @property
    def target_count(self) -> int:
        """Effective slot capacity after dedupe (HUD denominator)."""
        return len(self._targets)

    def vertices(self) -> list[int]:
        return [cp.vertex for cp in self._items]

    def next_unrecorded_target(self) -> int | None:
        """Next equal-spaced target vertex, or ``None`` if all recorded."""
        if self._next_target_idx >= len(self._targets):
            return None
        return int(self._targets[self._next_target_idx])

    def __len__(self) -> int:
        return len(self._items)

    def best_at_or_before(self, vertex: int) -> GridCheckpoint | None:
        best: GridCheckpoint | None = None
        for cp in self._items:
            if cp.vertex <= vertex and (best is None or cp.vertex > best.vertex):
                best = cp
        return best

    def resolve_chunks(self, checkpoint: GridCheckpoint, chunk_size: int) -> dict[tuple[int, int, int], object]:
        """Unpack non-FULL chunks for ``checkpoint`` (base + deltas in its GOP)."""
        idx = self._items.index(checkpoint)
        base_idx = idx
        while not self._items[base_idx].is_base:
            base_idx -= 1

        merged: dict[tuple[int, int, int], object] = dict(self._items[base_idx].data)
        for cp in self._items[base_idx + 1 : idx + 1]:
            for key, val in cp.data.items():
                if val is _REMOVED:
                    merged.pop(key, None)
                else:
                    merged[key] = val

        return {key: _unpack_chunk_state(val, chunk_size) for key, val in merged.items()}

    def maybe_record(
        self,
        vertex: int,
        occupancy,
        changed_keys: set[tuple[int, int, int]] | None = None,
    ) -> bool:
        """Snapshot at ``vertex`` if the next equal-spaced target is reached.

        ``occupancy`` is a :class:`ChunkedVoxelGrid` or a backend with ``.grid``.
        ``changed_keys`` are chunks carved since the last CP (``None`` → base).
        """
        grid = occupancy.grid if hasattr(occupancy, "grid") else occupancy
        vertex = int(vertex)
        if vertex <= 0 or self._next_target_idx >= len(self._targets):
            return False
        target = self._targets[self._next_target_idx]
        if vertex < target:
            return False
        if self._items and vertex <= self._items[-1].vertex:
            return False

        force_base = changed_keys is None or not self._items or len(self._items) % self.base_interval == 0

        if force_base:
            raw, _ = grid.snapshot_non_full()
            packed = {key: _pack_chunk_state(state) for key, state in raw.items()}
            nbytes = sum(_packed_nbytes(v) for v in packed.values())
            laser_snap = _laser_capture(occupancy, full=True)
            nbytes += laser_snapshot_nbytes(laser_snap)
            cp = GridCheckpoint(vertex=vertex, is_base=True, data=packed, nbytes=nbytes, laser=laser_snap)
            self._last_full_map = dict(packed)
        else:
            delta: dict[tuple[int, int, int], object] = {}
            for key in changed_keys:
                state = grid.get_chunk_state(ChunkCoord(*key))
                if state is CHUNK_FULL:
                    if key in self._last_full_map:
                        delta[key] = _REMOVED
                    continue
                packed_state = _pack_chunk_state(state)
                prev = self._last_full_map.get(key)
                if prev is None or not _packed_equal(prev, packed_state):
                    delta[key] = packed_state
            # Empty deltas are valid seek anchors (air cuts / no-op carves).
            nbytes = sum(_packed_nbytes(v) for v in delta.values())
            laser_snap = _laser_capture(occupancy, full=False)
            nbytes += laser_snapshot_nbytes(laser_snap)
            cp = GridCheckpoint(vertex=vertex, is_base=False, data=delta, nbytes=nbytes, laser=laser_snap)
            for key, val in delta.items():
                if val is _REMOVED:
                    self._last_full_map.pop(key, None)
                else:
                    self._last_full_map[key] = val

        self._items.append(cp)
        self._next_target_idx += 1
        while self._next_target_idx < len(self._targets) and self._targets[self._next_target_idx] <= vertex:
            self._next_target_idx += 1
        return True


def _laser_capture(occupancy, *, full: bool) -> object | None:
    fn = getattr(occupancy, "laser_checkpoint_full" if full else "laser_checkpoint_delta", None)
    if fn is None:
        return None
    return fn()


def restore_voxel_checkpoint(backend, store: CheckpointStore, checkpoint: GridCheckpoint) -> set:
    """Apply ``checkpoint`` onto ``backend.grid``. Returns restored chunk keys."""
    grid = backend.grid
    chunks = store.resolve_chunks(checkpoint, grid.chunk_size)
    grid.restore_non_full(chunks)
    restore_laser = getattr(backend, "_restore_laser_payload", None)
    if restore_laser is not None:
        idx = store._items.index(checkpoint)
        base_idx = idx
        while not store._items[base_idx].is_base:
            base_idx -= 1
        for i, cp in enumerate(store._items[base_idx : idx + 1]):
            restore_laser(cp.laser, occupancy_kind="full" if i == 0 else "delta")
    return set(chunks.keys())
