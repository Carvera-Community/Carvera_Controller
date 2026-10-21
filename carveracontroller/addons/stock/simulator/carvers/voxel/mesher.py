"""Face-culling mesher for carved voxel chunks -> Kivy Mesh buffers.

Meshing goes through the native stock extension (cut simulation requires
it); without the extension these helpers raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from carveracontroller.addons.stock.simulator.mesh_format import default_stock_color

if TYPE_CHECKING:
    from carveracontroller.addons.stock.simulator.carvers.array_mesh import PackedMesh

    from .grid import ChunkCoord, ChunkedVoxelGrid


def _neighbor_face_token(grid, coord, face):
    """Empty (None), solid (True), or a uint8 slice for one neighboring face."""
    from .grid import CHUNK_EMPTY, CHUNK_FULL

    cx, cy, cz = coord.cx, coord.cy, coord.cz
    if not (0 <= cx < grid.n_chunks_x and 0 <= cy < grid.n_chunks_y and 0 <= cz < grid.n_chunks_z):
        return None
    state = grid.get_chunk_state(coord)
    if state is CHUNK_EMPTY:
        return None
    if state is CHUNK_FULL or not isinstance(state, np.ndarray):
        return True
    axis, index = face
    if axis == "x":
        sl = state[index, :, :]
    elif axis == "y":
        sl = state[:, index, :]
    else:
        sl = state[:, :, index]
    if not np.any(sl):
        return None
    if bool(np.all(sl)):
        return True
    return np.ascontiguousarray(sl, dtype=np.uint8)


def _face_modes_and_arrays(tokens: list):
    modes = []
    faces = []
    for token in tokens:
        if token is None:
            modes.append(0)
            faces.append(None)
        elif token is True:
            modes.append(1)
            faces.append(None)
        else:
            modes.append(2)
            faces.append(token)
    return modes, faces


def _native_chunk_mesh(grid, coord, occupancy, valid, color):
    """Mesh one chunk via the native extension (cut simulation requires it)."""
    from carveracontroller.addons.stock.simulator import native as native_mod

    from .grid import ChunkCoord as CC

    specs = (
        (CC(coord.cx + 1, coord.cy, coord.cz), ("x", 0)),
        (CC(coord.cx - 1, coord.cy, coord.cz), ("x", -1)),
        (CC(coord.cx, coord.cy + 1, coord.cz), ("y", 0)),
        (CC(coord.cx, coord.cy - 1, coord.cz), ("y", -1)),
        (CC(coord.cx, coord.cy, coord.cz + 1), ("z", 0)),
        (CC(coord.cx, coord.cy, coord.cz - 1), ("z", -1)),
    )
    tokens = [_neighbor_face_token(grid, ncoord, face) for ncoord, face in specs]
    modes, faces = _face_modes_and_arrays(tokens)
    occ = None if occupancy is None else np.ascontiguousarray(occupancy, dtype=np.uint8)
    return native_mod.mesh_voxel_chunk_arrays(
        occ,
        None if valid is None else np.ascontiguousarray(valid, dtype=np.uint8),
        modes,
        faces,
        cs=int(grid.chunk_size),
        origin=grid.chunk_world_origin(coord),
        voxel=float(grid.voxel_size),
        color=color,
    )


def mesh_chunk(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    occupancy: np.ndarray,
    color: tuple[float, float, float, float] | None = None,
) -> list[PackedMesh]:
    """Build a triangle mesh for the exposed faces of one chunk.

    Returns a list of ``(vertices, indices, VERTEX_FORMAT)`` meshes, one per GLES draw
    (usually one), or an empty list if there is nothing to draw.
    Vertex positions are in **world millimetres** (caller scales into viewer space).
    Coplanar unit faces are greedily merged; vertices/indices are ``array.array``.
    """
    if color is None:
        color = default_stock_color()
    valid = None if grid._chunk_fully_in_bounds(coord) else grid._valid_mask(coord)
    cs = grid.chunk_size
    if occupancy.shape != (cs, cs, cs):
        raise ValueError(f"occupancy shape {occupancy.shape} != ({cs},{cs},{cs})")
    return _native_chunk_mesh(grid, coord, occupancy, valid, color)


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
) -> list[PackedMesh]:
    """Mesh one chunk from its current state (FULL / EMPTY / array)."""
    from .grid import CHUNK_EMPTY, CHUNK_FULL

    if state is None:
        state = grid.get_chunk_state(coord)
    if state is CHUNK_EMPTY:
        return []
    if state is CHUNK_FULL:
        return mesh_full_chunk(grid, coord)
    if isinstance(state, np.ndarray):
        return mesh_chunk(grid, coord, state)
    return []


def mesh_full_chunk(
    grid: ChunkedVoxelGrid,
    coord: ChunkCoord,
    color: tuple[float, float, float, float] | None = None,
) -> list[PackedMesh]:
    """Mesh an implicit FULL chunk from neighbour faces (no 16³ occupancy)."""
    if color is None:
        color = default_stock_color()
    if not grid._chunk_fully_in_bounds(coord):
        return mesh_chunk(grid, coord, solid_occupancy_for_chunk(grid, coord), color)

    return _native_chunk_mesh(grid, coord, None, None, color)


def mesh_dirty_chunks(
    grid: ChunkedVoxelGrid,
    dirty_chunk_coords: set[tuple[int, int, int]],
) -> dict[tuple[int, int, int], list[PackedMesh]]:
    """Mesh all dirty chunks. An empty list means the chunk mesh should be removed."""
    from .grid import CHUNK_EMPTY, ChunkCoord

    result: dict[tuple[int, int, int], list[PackedMesh]] = {}
    for key in dirty_chunk_coords:
        coord = ChunkCoord(*key)
        if not (
            0 <= coord.cx < grid.n_chunks_x and 0 <= coord.cy < grid.n_chunks_y and 0 <= coord.cz < grid.n_chunks_z
        ):
            continue
        state = grid.get_chunk_state(coord)
        if state is CHUNK_EMPTY:
            result[key] = []
            continue
        if isinstance(state, np.ndarray):
            grid.maybe_collapse_chunk(coord, state)
            state = grid.get_chunk_state(coord)
            if state is CHUNK_EMPTY:
                result[key] = []
                continue
        result[key] = mesh_chunk_state(grid, coord, state)
    return result
