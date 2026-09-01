"""Equal-spaced checkpoints for array occupancy (heightmap / cylindrical)."""

from __future__ import annotations

from dataclasses import dataclass

from carveracontroller.addons.stock.simulator.carvers.array_mesh import compressed_nbytes
from carveracontroller.addons.stock.simulator.carvers.laser_map import laser_snapshot_nbytes


def _equal_spaced_targets(path_vertex_count: int, slot_count: int) -> list[int]:
    v = int(path_vertex_count)
    n = max(1, int(slot_count))
    if v < 2:
        return []
    last = v - 1
    return list(dict.fromkeys(t for t in (int(round(i * last / n)) for i in range(1, n + 1)) if t > 0))


def snapshot_nbytes(payload: object) -> int:
    """Byte estimate for a ``("full"|"delta", occupancy[, extra...])`` payload."""
    if payload is None:
        return 0
    extra = 0
    occ = payload
    if isinstance(payload, tuple) and len(payload) >= 3 and payload[0] in ("full", "delta"):
        extra = sum(laser_snapshot_nbytes(blob) for blob in payload[2:])
        occ = payload[:2]
    if isinstance(occ, tuple) and len(occ) == 2:
        kind, data = occ
        if kind == "full":
            return compressed_nbytes(data) + extra
        if kind == "delta" and isinstance(data, dict):
            return sum(int(v.nbytes) if hasattr(v, "nbytes") else 64 for v in data.values()) + extra
    if hasattr(payload, "nbytes"):
        return int(payload.nbytes) + extra
    return 64 + extra


@dataclass(frozen=True)
class ArrayCheckpoint:
    vertex: int
    is_base: bool
    payload: object
    nbytes: int


class ArrayCheckpointStore:
    """Checkpoints holding opaque backend snapshot payloads (full array / tile deltas)."""

    def __init__(self, slot_count: int = 1024, base_interval: int = 8):
        self.slot_count = max(1, int(slot_count))
        self.base_interval = max(1, int(base_interval))
        self._path_vertex_count = 0
        self._targets: list[int] = []
        self._next_target_idx = 0
        self._items: list[ArrayCheckpoint] = []
        self._last_full_payload: object | None = None

    def clear(self) -> None:
        self._items.clear()
        self._last_full_payload = None
        self._next_target_idx = 0

    def set_path_vertex_count(self, n: int) -> None:
        n = max(0, int(n))
        if n == self._path_vertex_count:
            return
        self._path_vertex_count = n
        self._targets = _equal_spaced_targets(n, self.slot_count)
        self.clear()

    @property
    def target_count(self) -> int:
        return len(self._targets)

    def vertices(self) -> list[int]:
        return [cp.vertex for cp in self._items]

    def next_unrecorded_target(self) -> int | None:
        if self._next_target_idx >= len(self._targets):
            return None
        return int(self._targets[self._next_target_idx])

    def __len__(self) -> int:
        return len(self._items)

    def best_at_or_before(self, vertex: int) -> ArrayCheckpoint | None:
        best: ArrayCheckpoint | None = None
        for cp in self._items:
            if cp.vertex <= vertex and (best is None or cp.vertex > best.vertex):
                best = cp
        return best

    def resolve_payload(self, checkpoint: ArrayCheckpoint) -> object:
        """Return a full snapshot payload for ``checkpoint`` (base + deltas)."""
        idx = self._items.index(checkpoint)
        base_idx = idx
        while not self._items[base_idx].is_base:
            base_idx -= 1
        if base_idx == idx and self._items[base_idx].is_base:
            return self._items[base_idx].payload
        return [cp.payload for cp in self._items[base_idx : idx + 1]]

    def maybe_record(
        self,
        vertex: int,
        backend,
        changed_keys: set[tuple[int, int, int]] | None = None,
    ) -> bool:
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
            payload = backend.snapshot_full()
            nbytes = snapshot_nbytes(payload)
            cp = ArrayCheckpoint(vertex=vertex, is_base=True, payload=payload, nbytes=nbytes)
            self._last_full_payload = payload
        else:
            payload = backend.snapshot_changed(changed_keys)
            nbytes = snapshot_nbytes(payload)
            cp = ArrayCheckpoint(vertex=vertex, is_base=False, payload=payload, nbytes=nbytes)

        self._items.append(cp)
        self._next_target_idx += 1
        while self._next_target_idx < len(self._targets) and self._targets[self._next_target_idx] <= vertex:
            self._next_target_idx += 1
        return True


def restore_array_checkpoint(backend, store: ArrayCheckpointStore, checkpoint: ArrayCheckpoint) -> set:
    """Restore backend to ``checkpoint``; return dirty keys."""
    payloads = store.resolve_payload(checkpoint)
    if isinstance(payloads, list):
        dirty: set = set()
        for payload in payloads:
            dirty |= backend.restore(payload)
        return dirty
    return backend.restore(payloads)
