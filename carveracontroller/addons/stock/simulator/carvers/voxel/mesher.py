"""Face-culling mesher for carved voxel chunks -> Kivy Mesh buffers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.array_mesh import pack_quad_mesh
from carveracontroller.addons.stock.simulator.mesh_format import DEFAULT_COLOR, VERTEX_FORMAT

if TYPE_CHECKING:
    from .grid import ChunkCoord, ChunkedVoxelGrid

# Face offsets: (axis, sign) — greedy merge emits world quads in CCW order
# matching the former per-voxel corner tables when viewed from outside.
_FACES = (
    (0, 1),
    (0, -1),
    (1, 1),
    (1, -1),
    (2, 1),
    (2, -1),
)

_EMPTY_I32 = np.empty(0, dtype=np.int32)
_EMPTY_QUADS = np.empty((0, 4, 3), dtype=np.float32)


def mesh_chunk(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    occupancy: np.ndarray,
    color: tuple[float, float, float, float] = DEFAULT_COLOR,
) -> tuple | None:
    """Build a triangle mesh for the exposed faces of one chunk.

    Returns ``(vertices, indices, VERTEX_FORMAT)`` or ``None`` if nothing to draw.
    Vertex positions are in **world millimetres** (caller scales into viewer space).
    Coplanar unit faces are greedily merged; vertices/indices are ``array.array``.
    """
    cs = grid.chunk_size
    if occupancy.shape != (cs, cs, cs):
        raise ValueError(f"occupancy shape {occupancy.shape} != ({cs},{cs},{cs})")

    # Ignore padding outside the logical stock grid (those voxels must stay empty).
    solid = occupancy.astype(bool) & grid._valid_mask(coord)
    if not solid.any():
        return None

    neighbors = _neighbor_solid_maps(grid, coord, solid)
    ox, oy, oz = grid.chunk_world_origin(coord)
    vs = float(grid.voxel_size)

    parts_c: list[np.ndarray] = []
    parts_n: list[np.ndarray] = []
    for axis, sign in _FACES:
        other = neighbors[axis][1 if sign > 0 else 0]
        exposed = solid & ~other
        if not exposed.any():
            continue
        quads = _merged_face_quads(exposed, axis, sign, ox, oy, oz, vs)
        if quads.shape[0] == 0:
            continue
        nrm = np.zeros((quads.shape[0], 3), dtype=np.float32)
        nrm[:, axis] = np.float32(sign)
        parts_c.append(quads)
        parts_n.append(nrm)

    return _pack_parts(parts_c, parts_n, color)


def _pack_parts(
    parts_c: list[np.ndarray],
    parts_n: list[np.ndarray],
    color: tuple[float, float, float, float],
) -> tuple | None:
    if not parts_c:
        return None
    packed = pack_quad_mesh(np.concatenate(parts_c, axis=0), np.concatenate(parts_n, axis=0), color)
    if packed is None:
        return None
    verts, indices, _fmt = packed
    return verts, indices, VERTEX_FORMAT


def _as_xyz(x, y, z) -> np.ndarray:
    return np.stack(
        (
            np.asarray(x, dtype=np.float32),
            np.asarray(y, dtype=np.float32),
            np.asarray(z, dtype=np.float32),
        ),
        axis=-1,
    )


def _greedy_rects(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Axis-aligned rectangles covering True cells. Returns ``i0,j0,i1,j1`` exclusive."""
    rows, cols = mask.shape
    if rows == 0 or cols == 0 or not mask.any():
        return _EMPTY_I32, _EMPTY_I32, _EMPTY_I32, _EMPTY_I32
    if bool(mask.all()):
        return (
            np.array([0], dtype=np.int32),
            np.array([0], dtype=np.int32),
            np.array([rows], dtype=np.int32),
            np.array([cols], dtype=np.int32),
        )
    used = np.empty((rows, cols), dtype=bool)
    np.logical_not(mask, out=used)
    i0s: list[int] = []
    j0s: list[int] = []
    i1s: list[int] = []
    j1s: list[int] = []
    for i in range(rows):
        j = 0
        while j < cols:
            if used[i, j]:
                j += 1
                continue
            w = 1
            while j + w < cols and not used[i, j + w]:
                w += 1
            d = 1
            while i + d < rows:
                if used[i + d, j : j + w].any():
                    break
                d += 1
            used[i : i + d, j : j + w] = True
            i0s.append(i)
            j0s.append(j)
            i1s.append(i + d)
            j1s.append(j + w)
            j += w
    return (
        np.asarray(i0s, dtype=np.int32),
        np.asarray(j0s, dtype=np.int32),
        np.asarray(i1s, dtype=np.int32),
        np.asarray(j1s, dtype=np.int32),
    )


def _merged_face_quads(
    exposed: np.ndarray,
    axis: int,
    sign: int,
    ox: float,
    oy: float,
    oz: float,
    vs: float,
) -> np.ndarray:
    """Greedy-merge exposed unit faces of one axis/sign into world-space quads."""
    if axis == 0:
        hits = np.flatnonzero(exposed.any(axis=(1, 2)))
        masks = (exposed[int(i), :, :] for i in hits)
    elif axis == 1:
        hits = np.flatnonzero(exposed.any(axis=(0, 2)))
        masks = (exposed[:, int(j), :] for j in hits)
    else:
        hits = np.flatnonzero(exposed.any(axis=(0, 1)))
        masks = (exposed[:, :, int(k)] for k in hits)
    parts: list[np.ndarray] = []
    for index, mask in zip(hits, masks):
        quads = _quads_from_2d_mask(mask, axis, sign, int(index), ox, oy, oz, vs)
        if quads.shape[0]:
            parts.append(quads)
    if not parts:
        return _EMPTY_QUADS
    return np.concatenate(parts, axis=0)


def _quads_from_2d_mask(
    mask: np.ndarray,
    axis: int,
    sign: int,
    index: int,
    ox: float,
    oy: float,
    oz: float,
    vs: float,
) -> np.ndarray:
    """World quads for one axis-aligned slice of exposed faces."""
    i0, j0, i1, j1 = _greedy_rects(mask)
    if i0.size == 0:
        return _EMPTY_QUADS
    vs32 = np.float32(vs)
    ox32, oy32, oz32 = np.float32(ox), np.float32(oy), np.float32(oz)
    face = 1 if sign > 0 else 0
    if axis == 0:
        x = ox32 + (np.int32(index) + face) * vs32
        wy0 = oy32 + i0 * vs32
        wz0 = oz32 + j0 * vs32
        wy1 = oy32 + i1 * vs32
        wz1 = oz32 + j1 * vs32
        xx = np.full(i0.shape, x, dtype=np.float32)
        if sign > 0:
            return np.stack(
                (_as_xyz(xx, wy0, wz0), _as_xyz(xx, wy1, wz0), _as_xyz(xx, wy1, wz1), _as_xyz(xx, wy0, wz1)),
                axis=1,
            )
        return np.stack(
            (_as_xyz(xx, wy0, wz0), _as_xyz(xx, wy0, wz1), _as_xyz(xx, wy1, wz1), _as_xyz(xx, wy1, wz0)),
            axis=1,
        )
    if axis == 1:
        y = oy32 + (np.int32(index) + face) * vs32
        wx0 = ox32 + i0 * vs32
        wz0 = oz32 + j0 * vs32
        wx1 = ox32 + i1 * vs32
        wz1 = oz32 + j1 * vs32
        yy = np.full(i0.shape, y, dtype=np.float32)
        if sign > 0:
            return np.stack(
                (_as_xyz(wx0, yy, wz0), _as_xyz(wx0, yy, wz1), _as_xyz(wx1, yy, wz1), _as_xyz(wx1, yy, wz0)),
                axis=1,
            )
        return np.stack(
            (_as_xyz(wx0, yy, wz0), _as_xyz(wx1, yy, wz0), _as_xyz(wx1, yy, wz1), _as_xyz(wx0, yy, wz1)),
            axis=1,
        )
    z = oz32 + (np.int32(index) + face) * vs32
    wx0 = ox32 + i0 * vs32
    wy0 = oy32 + j0 * vs32
    wx1 = ox32 + i1 * vs32
    wy1 = oy32 + j1 * vs32
    zz = np.full(i0.shape, z, dtype=np.float32)
    if sign > 0:
        return np.stack(
            (_as_xyz(wx0, wy0, zz), _as_xyz(wx1, wy0, zz), _as_xyz(wx1, wy1, zz), _as_xyz(wx0, wy1, zz)),
            axis=1,
        )
    return np.stack(
        (_as_xyz(wx0, wy0, zz), _as_xyz(wx0, wy1, zz), _as_xyz(wx1, wy1, zz), _as_xyz(wx1, wy0, zz)),
        axis=1,
    )


def _neighbor_solid_maps(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    solid: np.ndarray,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """For each axis, return (neg_neighbor_solid, pos_neighbor_solid) aligned to ``solid``.

    For a voxel at local (i,j,k), the +X neighbour solidness is in ``pos[i,j,k]``
    (i.e. solidness of voxel i+1, or the adjacent chunk's edge, or False if OOB).
    """
    from .grid import ChunkCoord as CC

    cs = grid.chunk_size
    result: list[tuple[np.ndarray, np.ndarray]] = []

    for axis in range(3):
        # Shift within chunk
        if axis == 0:
            pos_internal = np.zeros_like(solid)
            pos_internal[:-1, :, :] = solid[1:, :, :]
            neg_internal = np.zeros_like(solid)
            neg_internal[1:, :, :] = solid[:-1, :, :]
            # Edge strips from neighbouring chunks
            pos_edge = _chunk_face_solid(grid, CC(coord.cx + 1, coord.cy, coord.cz), face=("x", 0))
            neg_edge = _chunk_face_solid(grid, CC(coord.cx - 1, coord.cy, coord.cz), face=("x", -1))
            if pos_edge is not None:
                pos_internal[-1, :, :] = pos_edge
            if neg_edge is not None:
                neg_internal[0, :, :] = neg_edge
        elif axis == 1:
            pos_internal = np.zeros_like(solid)
            pos_internal[:, :-1, :] = solid[:, 1:, :]
            neg_internal = np.zeros_like(solid)
            neg_internal[:, 1:, :] = solid[:, :-1, :]
            pos_edge = _chunk_face_solid(grid, CC(coord.cx, coord.cy + 1, coord.cz), face=("y", 0))
            neg_edge = _chunk_face_solid(grid, CC(coord.cx, coord.cy - 1, coord.cz), face=("y", -1))
            if pos_edge is not None:
                pos_internal[:, -1, :] = pos_edge
            if neg_edge is not None:
                neg_internal[:, 0, :] = neg_edge
        else:
            pos_internal = np.zeros_like(solid)
            pos_internal[:, :, :-1] = solid[:, :, 1:]
            neg_internal = np.zeros_like(solid)
            neg_internal[:, :, 1:] = solid[:, :, :-1]
            pos_edge = _chunk_face_solid(grid, CC(coord.cx, coord.cy, coord.cz + 1), face=("z", 0))
            neg_edge = _chunk_face_solid(grid, CC(coord.cx, coord.cy, coord.cz - 1), face=("z", -1))
            if pos_edge is not None:
                pos_internal[:, :, -1] = pos_edge
            if neg_edge is not None:
                neg_internal[:, :, 0] = neg_edge

        result.append((neg_internal, pos_internal))
    return result


def _chunk_face_solid(grid, coord, face) -> np.ndarray | None:
    """Return a 2D boolean face from a neighbouring chunk, or None if empty/OOB.

    ``face`` is ``('x'|'y'|'z', 0|-1)`` selecting the low (0) or high (-1) face.
    """
    from .grid import CHUNK_EMPTY, CHUNK_FULL

    cx, cy, cz = coord.cx, coord.cy, coord.cz
    if not (0 <= cx < grid.n_chunks_x and 0 <= cy < grid.n_chunks_y and 0 <= cz < grid.n_chunks_z):
        return None  # outside stock → treated as empty (caller leaves zeros)

    state = grid.get_chunk_state(coord)
    axis, index = face
    cs = grid.chunk_size

    if state is CHUNK_EMPTY:
        return np.zeros((cs, cs), dtype=bool)
    if state is CHUNK_FULL:
        # Untouched solid
        return np.ones((cs, cs), dtype=bool)
    if not isinstance(state, np.ndarray):
        return np.ones((cs, cs), dtype=bool)

    arr = state
    if axis == "x":
        return arr[index, :, :].astype(bool)
    if axis == "y":
        return arr[:, index, :].astype(bool)
    return arr[:, :, index].astype(bool)


def solid_occupancy_for_chunk(grid: ChunkedVoxelGrid, coord: ChunkCoord) -> np.ndarray:
    """Build a solid occupancy array for a FULL (or missing) chunk without storing it."""
    cs = grid.chunk_size
    arr = np.zeros((cs, cs, cs), dtype=np.uint8)
    arr[grid._valid_mask(coord)] = 1
    return arr


def mesh_chunk_state(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    state: object | None = None,
) -> tuple | None:
    """Mesh one chunk from its current state (FULL / EMPTY / array)."""
    from .grid import CHUNK_EMPTY, CHUNK_FULL

    if state is None:
        state = grid.get_chunk_state(coord)
    if state is CHUNK_EMPTY:
        return None
    if state is CHUNK_FULL:
        return mesh_full_chunk(grid, coord)
    if isinstance(state, np.ndarray):
        return mesh_chunk(grid, coord, state)
    return None


def mesh_full_chunk(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    color: tuple[float, float, float, float] = DEFAULT_COLOR,
) -> tuple | None:
    """Mesh an implicit FULL chunk from neighbour faces (no 16³ occupancy)."""
    from .grid import ChunkCoord as CC

    if not grid._chunk_fully_in_bounds(coord):
        return mesh_chunk(grid, coord, solid_occupancy_for_chunk(grid, coord), color)

    cs = grid.chunk_size
    ox, oy, oz = grid.chunk_world_origin(coord)
    vs = float(grid.voxel_size)
    parts_c: list[np.ndarray] = []
    parts_n: list[np.ndarray] = []
    specs = (
        (0, 1, CC(coord.cx + 1, coord.cy, coord.cz), ("x", 0), cs - 1),
        (0, -1, CC(coord.cx - 1, coord.cy, coord.cz), ("x", -1), 0),
        (1, 1, CC(coord.cx, coord.cy + 1, coord.cz), ("y", 0), cs - 1),
        (1, -1, CC(coord.cx, coord.cy - 1, coord.cz), ("y", -1), 0),
        (2, 1, CC(coord.cx, coord.cy, coord.cz + 1), ("z", 0), cs - 1),
        (2, -1, CC(coord.cx, coord.cy, coord.cz - 1), ("z", -1), 0),
    )
    for axis, sign, ncoord, face, index in specs:
        edge = _chunk_face_solid(grid, ncoord, face)
        if edge is None:
            mask = np.ones((cs, cs), dtype=bool)
        else:
            if bool(edge.all()):
                continue
            mask = ~edge
            if not mask.any():
                continue
        quads = _quads_from_2d_mask(mask, axis, sign, index, ox, oy, oz, vs)
        if quads.shape[0] == 0:
            continue
        nrm = np.zeros((quads.shape[0], 3), dtype=np.float32)
        nrm[:, axis] = np.float32(sign)
        parts_c.append(quads)
        parts_n.append(nrm)
    return _pack_parts(parts_c, parts_n, color)


def mesh_dirty_chunks(
    grid: ChunkedVoxelGrid,
    dirty_chunk_coords: set[tuple[int, int, int]],
) -> dict[tuple[int, int, int], tuple | None]:
    """Mesh all dirty chunks. ``None`` means the chunk mesh should be removed."""
    from .grid import CHUNK_EMPTY, ChunkCoord

    result: dict[tuple[int, int, int], tuple | None] = {}
    for key in dirty_chunk_coords:
        coord = ChunkCoord(*key)
        if not (
            0 <= coord.cx < grid.n_chunks_x and 0 <= coord.cy < grid.n_chunks_y and 0 <= coord.cz < grid.n_chunks_z
        ):
            continue
        state = grid.get_chunk_state(coord)
        if state is CHUNK_EMPTY:
            result[key] = None
            continue
        if isinstance(state, np.ndarray):
            grid.maybe_collapse_chunk(coord, state)
            state = grid.get_chunk_state(coord)
            if state is CHUNK_EMPTY:
                result[key] = None
                continue
        packed = mesh_chunk_state(grid, coord, state)
        result[key] = packed
    return result
