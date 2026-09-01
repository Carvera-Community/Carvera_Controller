"""Chunked dense voxel occupancy grid for stock simulation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from carveracontroller.addons.stock.simulator.simulation_quality import (
    DEFAULT_VOXEL_RESOLUTION,
    MAX_CELL_SIZE_MM,
    MIN_CELL_SIZE_MM,
    VOXEL_TARGET_BY_LEVEL,
    pick_cell_size_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds

# Sentinel markers for untouched / fully emptied chunks (avoid allocating arrays).
CHUNK_FULL = object()
CHUNK_EMPTY = object()

DEFAULT_CHUNK_SIZE = 16
MIN_VOXEL_SIZE_MM = MIN_CELL_SIZE_MM["voxel"]
MAX_VOXEL_SIZE_MM = MAX_CELL_SIZE_MM["voxel"]


def pick_voxel_size_mm(
    bounds: StockBounds,
    target: int = VOXEL_TARGET_BY_LEVEL[DEFAULT_VOXEL_RESOLUTION],
) -> float:
    """Choose a voxel size so the longest stock axis has roughly ``target`` voxels."""
    return pick_cell_size_mm(bounds, carver="voxel", target=target)


@dataclass(frozen=True)
class ChunkCoord:
    cx: int
    cy: int
    cz: int

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.cx, self.cy, self.cz)


class ChunkedVoxelGrid:
    """Sparse chunked occupancy grid over a stock AABB.

    Each chunk is either:
    - ``CHUNK_FULL``: never carved (all solid, no array allocated)
    - ``CHUNK_EMPTY``: fully carved away
    - ``np.ndarray`` of shape ``(chunk_size,)*3``, dtype uint8 (1=solid, 0=empty)

    Coordinates are world millimetres; voxel indices are axis-aligned from
    ``bounds.min_*`` with positive X/Y/Z.
    """

    def __init__(
        self,
        bounds: StockBounds,
        voxel_size_mm: float,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        if voxel_size_mm <= 0:
            raise ValueError("voxel_size_mm must be positive")
        if chunk_size < 2:
            raise ValueError("chunk_size must be >= 2")

        self.bounds = bounds
        self.voxel_size = float(voxel_size_mm)
        self.chunk_size = int(chunk_size)

        sx, sy, sz = bounds.size
        self.nx = max(1, int(np.ceil(sx / self.voxel_size)))
        self.ny = max(1, int(np.ceil(sy / self.voxel_size)))
        self.nz = max(1, int(np.ceil(sz / self.voxel_size)))

        self.n_chunks_x = max(1, int(np.ceil(self.nx / self.chunk_size)))
        self.n_chunks_y = max(1, int(np.ceil(self.ny / self.chunk_size)))
        self.n_chunks_z = max(1, int(np.ceil(self.nz / self.chunk_size)))

        # Lazily populated: missing key == CHUNK_FULL (untouched solid stock).
        self._chunks: dict[tuple[int, int, int], object] = {}
        # Interior chunks are entirely in-bounds; share one mask. Edge chunks cache.
        cs = self.chunk_size
        self._full_valid = np.ones((cs, cs, cs), dtype=bool)
        self._valid_mask_cache: dict[tuple[int, int, int], np.ndarray] = {}

    def reset(self) -> None:
        self._chunks.clear()

    def snapshot_non_full(self) -> tuple[dict[tuple[int, int, int], object], int]:
        """Copy EMPTY / array chunks only (missing key ⇒ FULL).

        Returns ``(chunks, nbytes)`` where ``nbytes`` estimates retained payload.
        """
        out: dict[tuple[int, int, int], object] = {}
        nbytes = 0
        for key, state in self._chunks.items():
            if state is CHUNK_FULL:
                continue
            if state is CHUNK_EMPTY:
                out[key] = CHUNK_EMPTY
                nbytes += 32  # key + sentinel overhead (approx)
            elif isinstance(state, np.ndarray):
                copied = state.copy()
                out[key] = copied
                nbytes += int(copied.nbytes)
        return out, nbytes

    def restore_non_full(self, chunks: dict[tuple[int, int, int], object]) -> None:
        """Replace grid contents from a :meth:`snapshot_non_full` payload."""
        self._chunks.clear()
        for key, state in chunks.items():
            if state is CHUNK_EMPTY:
                self._chunks[key] = CHUNK_EMPTY
            elif isinstance(state, np.ndarray):
                self._chunks[key] = state.copy()
            # Ignore unexpected FULL entries — absence already means FULL.

    def copy_chunks(self, keys: set[tuple[int, int, int]]) -> ChunkedVoxelGrid:
        """Deep-copy selected chunks into a new grid (same bounds / resolution).

        ``CHUNK_EMPTY`` is stored explicitly (absence means FULL). Array chunks
        are copied so the live grid can be mutated in place while the copy is
        meshed unlocked. FULL / missing keys are left absent.
        """
        out = ChunkedVoxelGrid(self.bounds, self.voxel_size, self.chunk_size)
        for key in keys:
            cx, cy, cz = key
            if not (0 <= cx < self.n_chunks_x and 0 <= cy < self.n_chunks_y and 0 <= cz < self.n_chunks_z):
                continue
            state = self.get_chunk_state(key)
            if state is CHUNK_EMPTY:
                out._chunks[key] = CHUNK_EMPTY
            elif isinstance(state, np.ndarray):
                out._chunks[key] = state.copy()
            # FULL / unexpected → leave absent (missing key ⇒ FULL).
        return out

    def world_to_voxel(self, x: float, y: float, z: float) -> tuple[int, int, int]:
        ix = int(np.floor((x - self.bounds.min_x) / self.voxel_size))
        iy = int(np.floor((y - self.bounds.min_y) / self.voxel_size))
        iz = int(np.floor((z - self.bounds.min_z) / self.voxel_size))
        return ix, iy, iz

    def voxel_center(self, ix: int, iy: int, iz: int) -> tuple[float, float, float]:
        return (
            self.bounds.min_x + (ix + 0.5) * self.voxel_size,
            self.bounds.min_y + (iy + 0.5) * self.voxel_size,
            self.bounds.min_z + (iz + 0.5) * self.voxel_size,
        )

    def chunk_of_voxel(self, ix: int, iy: int, iz: int) -> ChunkCoord:
        return ChunkCoord(
            ix // self.chunk_size,
            iy // self.chunk_size,
            iz // self.chunk_size,
        )

    def iter_chunks_in_aabb(
        self,
        min_x: float,
        min_y: float,
        min_z: float,
        max_x: float,
        max_y: float,
        max_z: float,
    ) -> Iterator[ChunkCoord]:
        """Yield chunk coords that overlap the given world AABB (clamped to grid)."""
        ix0, iy0, iz0 = self.world_to_voxel(min_x, min_y, min_z)
        ix1, iy1, iz1 = self.world_to_voxel(max_x, max_y, max_z)

        ix0 = max(0, min(self.nx - 1, ix0))
        iy0 = max(0, min(self.ny - 1, iy0))
        iz0 = max(0, min(self.nz - 1, iz0))
        ix1 = max(0, min(self.nx - 1, ix1))
        iy1 = max(0, min(self.ny - 1, iy1))
        iz1 = max(0, min(self.nz - 1, iz1))

        cx0 = ix0 // self.chunk_size
        cy0 = iy0 // self.chunk_size
        cz0 = iz0 // self.chunk_size
        cx1 = ix1 // self.chunk_size
        cy1 = iy1 // self.chunk_size
        cz1 = iz1 // self.chunk_size

        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                for cz in range(cz0, cz1 + 1):
                    if 0 <= cx < self.n_chunks_x and 0 <= cy < self.n_chunks_y and 0 <= cz < self.n_chunks_z:
                        yield ChunkCoord(cx, cy, cz)

    def get_chunk_state(self, coord: ChunkCoord | tuple[int, int, int]) -> object:
        key = coord.as_tuple() if isinstance(coord, ChunkCoord) else coord
        return self._chunks.get(key, CHUNK_FULL)

    def get_or_create_chunk(self, coord: ChunkCoord) -> np.ndarray | None:
        """Return a mutable occupancy array for carving, or None if already empty.

        FULL chunks are materialised as arrays that are solid only inside the
        logical grid (``nx/ny/nz``). Padding outside those extents stays empty
        so meshing cannot invent solid blocks beyond the stock AABB.
        """
        key = coord.as_tuple()
        state = self._chunks.get(key, CHUNK_FULL)
        if state is CHUNK_EMPTY:
            return None
        if state is CHUNK_FULL or key not in self._chunks:
            arr = np.zeros((self.chunk_size, self.chunk_size, self.chunk_size), dtype=np.uint8)
            arr[self._valid_mask(coord)] = 1
            self._chunks[key] = arr
            return arr
        return state  # type: ignore[return-value]

    def release_unmodified_full(self, coord: ChunkCoord) -> None:
        """Drop a just-materialised FULL chunk that was never carved (missing ⇒ FULL)."""
        self._chunks.pop(coord.as_tuple(), None)

    def _chunk_fully_in_bounds(self, coord: ChunkCoord) -> bool:
        """True when every local voxel of ``coord`` lies inside ``nx/ny/nz``."""
        cs = self.chunk_size
        return (coord.cx + 1) * cs <= self.nx and (coord.cy + 1) * cs <= self.ny and (coord.cz + 1) * cs <= self.nz

    def _valid_count(self, coord: ChunkCoord) -> int:
        """Number of in-bounds voxels in ``coord``."""
        if self._chunk_fully_in_bounds(coord):
            cs = self.chunk_size
            return cs * cs * cs
        return int(self._valid_mask(coord).sum())

    def _valid_mask(self, coord: ChunkCoord) -> np.ndarray:
        """Boolean mask of local voxels that lie inside the logical grid."""
        if self._chunk_fully_in_bounds(coord):
            return self._full_valid
        key = coord.as_tuple()
        cached = self._valid_mask_cache.get(key)
        if cached is not None:
            return cached
        cs = self.chunk_size
        ix0 = coord.cx * cs
        iy0 = coord.cy * cs
        iz0 = coord.cz * cs
        lx = np.arange(cs)
        mask = (
            ((ix0 + lx)[:, None, None] < self.nx)
            & ((iy0 + lx)[None, :, None] < self.ny)
            & ((iz0 + lx)[None, None, :] < self.nz)
        )
        self._valid_mask_cache[key] = mask
        return mask

    def maybe_collapse_chunk(
        self,
        coord: ChunkCoord,
        arr: np.ndarray,
        solid_count: int | None = None,
    ) -> None:
        """Collapse a fully-empty or fully-solid-in-bounds chunk to a sentinel."""
        key = coord.as_tuple()
        n = int(arr.sum()) if solid_count is None else int(solid_count)
        if n == 0:
            self._chunks[key] = CHUNK_EMPTY
            return
        n_valid = self._valid_count(coord)
        if n < n_valid:
            return
        if self._chunk_fully_in_bounds(coord):
            self._chunks[key] = CHUNK_FULL
            return
        valid = self._valid_mask(coord)
        if valid.any() and not arr[~valid].any():
            # All in-bounds voxels solid and no stray padding solid → FULL.
            self._chunks[key] = CHUNK_FULL

    def chunk_world_origin(self, coord: ChunkCoord) -> tuple[float, float, float]:
        """World-space min corner of the chunk's voxel (0,0,0)."""
        return (
            self.bounds.min_x + coord.cx * self.chunk_size * self.voxel_size,
            self.bounds.min_y + coord.cy * self.chunk_size * self.voxel_size,
            self.bounds.min_z + coord.cz * self.chunk_size * self.voxel_size,
        )

    def solid_voxel_count_approx(self) -> int:
        """Approximate remaining solid voxels (FULL chunks count as fully solid)."""
        total = self.nx * self.ny * self.nz
        cs = self.chunk_size
        chunk_voxels = cs * cs * cs
        for state in self._chunks.values():
            if state is CHUNK_EMPTY:
                total -= chunk_voxels
            elif state is not CHUNK_FULL and isinstance(state, np.ndarray):
                total -= int(chunk_voxels - state.sum())
        return max(0, total)

    def is_solid_at_world(self, x: float, y: float, z: float) -> bool:
        """Test occupancy at a world point (for unit tests)."""
        if not (
            self.bounds.min_x <= x < self.bounds.max_x
            and self.bounds.min_y <= y < self.bounds.max_y
            and self.bounds.min_z <= z < self.bounds.max_z
        ):
            return False
        ix, iy, iz = self.world_to_voxel(x, y, z)
        if not (0 <= ix < self.nx and 0 <= iy < self.ny and 0 <= iz < self.nz):
            return False
        coord = self.chunk_of_voxel(ix, iy, iz)
        state = self.get_chunk_state(coord)
        if state is CHUNK_FULL:
            return True
        if state is CHUNK_EMPTY:
            return False
        lx = ix - coord.cx * self.chunk_size
        ly = iy - coord.cy * self.chunk_size
        lz = iz - coord.cz * self.chunk_size
        return bool(state[lx, ly, lz])  # type: ignore[index]
