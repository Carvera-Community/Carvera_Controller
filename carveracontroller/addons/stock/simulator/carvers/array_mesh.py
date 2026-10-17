"""Shared mesh packing and tile-key helpers for dense array carvers."""

from __future__ import annotations

import array
import zlib
from collections.abc import Iterable

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.backend import TileKey
from carveracontroller.addons.stock.simulator.mesh_format import VERTEX_FORMAT, default_stock_color

_FLOATS_PER_VERT = 12
# GLES 2 Mesh: index values are uint16, and the index list itself cannot exceed 65535
MAX_KIVY_MESH_VERTS = 65500
MAX_KIVY_MESH_INDICES = 65535
_MAX_QUADS_PER_MESH = min(MAX_KIVY_MESH_VERTS // 4, MAX_KIVY_MESH_INDICES // 6)
# Largest multiple of 3 that is <= both caps, so a window of this many indices never
# references more than MAX_KIVY_MESH_VERTS distinct vertices.
_SPLIT_WINDOW_INDICES = (min(MAX_KIVY_MESH_INDICES, MAX_KIVY_MESH_VERTS) // 3) * 3

PackedMesh = tuple[array.array, array.array, list]


def tile_keys_from_window_mask(
    mask: np.ndarray,
    x0: int,
    y0: int,
    tile_size: int,
) -> set[TileKey]:
    """Tile keys covering True cells in a window whose origin is ``(x0, y0)``.

    Walks the overlapping tile grid and tests each tile with ``.any()`` so cost
    is O(tiles) rather than ``np.unique`` over every hit cell.
    """
    if mask.size == 0 or not mask.any():
        return set()
    ts = max(1, int(tile_size))
    rows, cols = mask.shape
    gx0, gy0 = int(x0), int(y0)
    tx0 = gx0 // ts
    ty0 = gy0 // ts
    tx1 = (gx0 + rows - 1) // ts
    ty1 = (gy0 + cols - 1) // ts
    out: set[TileKey] = set()
    for tx in range(tx0, tx1 + 1):
        x_lo = max(0, tx * ts - gx0)
        x_hi = min(rows, (tx + 1) * ts - gx0)
        for ty in range(ty0, ty1 + 1):
            y_lo = max(0, ty * ts - gy0)
            y_hi = min(cols, (ty + 1) * ts - gy0)
            if mask[x_lo:x_hi, y_lo:y_hi].any():
                out.add((int(tx), int(ty), 0))
    return out


def _as_f32_array(data: np.ndarray) -> array.array:
    buf = np.ascontiguousarray(data, dtype=np.float32).ravel()
    out = array.array("f")
    out.frombytes(buf.tobytes())
    return out


def _as_u16_array(data: np.ndarray) -> array.array:
    buf = np.ascontiguousarray(data, dtype=np.uint16).ravel()
    out = array.array("H")
    out.frombytes(buf.tobytes())
    return out


def compress_array(arr: np.ndarray) -> tuple[bytes, tuple[int, ...], str]:
    """zlib-compress a contiguous array (heightmaps compress extremely well)."""
    c = np.ascontiguousarray(arr)
    return zlib.compress(c.tobytes(), 1), tuple(int(s) for s in c.shape), c.dtype.str


def decompress_array(payload: object) -> np.ndarray:
    """Inverse of :func:`compress_array`. Also accepts a raw ndarray."""
    if isinstance(payload, np.ndarray):
        return payload
    data, shape, dtype = payload  # type: ignore[misc]
    return np.frombuffer(zlib.decompress(data), dtype=np.dtype(dtype)).reshape(shape).copy()


def compressed_nbytes(payload: object) -> int:
    if isinstance(payload, np.ndarray):
        return int(payload.nbytes)
    if isinstance(payload, tuple) and payload and isinstance(payload[0], (bytes, bytearray)):
        return int(len(payload[0]))
    return 64


def pack_quad_mesh(
    corners: np.ndarray,
    normals: np.ndarray,
    color: tuple[float, float, float, float],
) -> PackedMesh | None:
    """Pack ``(Q, 4, 3)`` quad corners + ``(Q, 3)`` normals into Kivy mesh buffers.

    ``Q`` must keep vertex count ≤ :data:`MAX_KIVY_MESH_VERTS`. Use
    :func:`pack_quad_meshes` when the field may be larger.

    Vertices/indices are ``array.array`` (Kivy's native Mesh storage) so packing
    does not materialise millions of Python floats.
    """
    if corners.size == 0:
        return None
    q = int(corners.shape[0])
    verts = np.zeros((q, 4, _FLOATS_PER_VERT), dtype=np.float32)
    verts[:, :, 0:3] = corners
    verts[:, :, 3:6] = normals[:, None, :]
    cr, cg, cb, ca = color
    verts[:, :, 6] = cr
    verts[:, :, 7] = cg
    verts[:, :, 8] = cb
    verts[:, :, 9] = ca
    base = np.arange(q, dtype=np.uint16) * 4
    idx = np.empty((q, 6), dtype=np.uint16)
    idx[:, 0] = base
    idx[:, 1] = base + 1
    idx[:, 2] = base + 2
    idx[:, 3] = base
    idx[:, 4] = base + 2
    idx[:, 5] = base + 3
    return _as_f32_array(verts), _as_u16_array(idx), VERTEX_FORMAT


def pack_quad_meshes(
    corners: np.ndarray,
    normals: np.ndarray,
    color: tuple[float, float, float, float],
) -> list[PackedMesh]:
    """Pack quads into one or more Kivy-safe meshes (uint16 values and index-list length)."""
    if corners.size == 0:
        return []
    q = int(corners.shape[0])
    out: list[PackedMesh] = []
    for start in range(0, q, _MAX_QUADS_PER_MESH):
        end = min(q, start + _MAX_QUADS_PER_MESH)
        packed = pack_quad_mesh(corners[start:end], normals[start:end], color)
        if packed is not None:
            out.append(packed)
    return out


def aabb_box_mesh(
    xmin: float,
    ymin: float,
    zmin: float,
    xmax: float,
    ymax: float,
    zmax: float,
    color: tuple[float, float, float, float] | None = None,
) -> PackedMesh | None:
    """Six outward quads for one solid box. A uniform shell is this, not a tile grid."""
    if color is None:
        color = default_stock_color()
    if xmax <= xmin or ymax <= ymin or zmax <= zmin:
        return None
    corners = np.array(
        (
            ((xmin, ymin, zmax), (xmax, ymin, zmax), (xmax, ymax, zmax), (xmin, ymax, zmax)),
            ((xmin, ymin, zmin), (xmin, ymax, zmin), (xmax, ymax, zmin), (xmax, ymin, zmin)),
            ((xmin, ymin, zmax), (xmin, ymax, zmax), (xmin, ymax, zmin), (xmin, ymin, zmin)),
            ((xmax, ymax, zmax), (xmax, ymin, zmax), (xmax, ymin, zmin), (xmax, ymax, zmin)),
            ((xmax, ymin, zmax), (xmin, ymin, zmax), (xmin, ymin, zmin), (xmax, ymin, zmin)),
            ((xmin, ymax, zmax), (xmax, ymax, zmax), (xmax, ymax, zmin), (xmin, ymax, zmin)),
        ),
        dtype=np.float32,
    )
    normals = np.array(
        ((0, 0, 1), (0, 0, -1), (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0)),
        dtype=np.float32,
    )
    return pack_quad_mesh(corners, normals, color)


def _split_indexed_mesh(verts: array.array, indices: array.array) -> list[PackedMesh]:
    """Break one triangle mesh into draws that fit both GLES Mesh caps.

    Triangles that straddle a split get their vertices copied into the next draw.
    """
    nv = len(verts) // _FLOATS_PER_VERT
    if nv <= 0 or len(indices) < 3:
        return []
    if nv <= MAX_KIVY_MESH_VERTS and len(indices) <= MAX_KIVY_MESH_INDICES:
        return [(verts, indices, VERTEX_FORMAT)]
    src_v = np.frombuffer(memoryview(verts), dtype=np.float32).reshape(nv, _FLOATS_PER_VERT)
    src_i = np.frombuffer(memoryview(indices), dtype=np.uint16)
    n_used = len(src_i) - len(src_i) % 3  # ignore a dangling partial triangle
    out: list[PackedMesh] = []
    # Fixed windows of whole triangles: a window of N indices touches at most N distinct
    # vertices, so both caps hold without tracking vertex counts.
    for start in range(0, n_used, _SPLIT_WINDOW_INDICES):
        window = src_i[start : min(start + _SPLIT_WINDOW_INDICES, n_used)]
        used, local = np.unique(window, return_inverse=True)
        out.append(
            (
                _as_f32_array(src_v[used]),
                _as_u16_array(local.reshape(-1)),
                VERTEX_FORMAT,
            )
        )
    return out


def coalesce_indexed_meshes(parts: Iterable) -> list[PackedMesh]:
    """Concatenate indexed meshes, splitting before either GLES Mesh cap."""
    out: list[PackedMesh] = []
    cur_v = array.array("f")
    cur_i = array.array("H")

    def flush() -> None:
        nonlocal cur_v, cur_i
        if len(cur_v) == 0:
            return
        out.append((cur_v, cur_i, VERTEX_FORMAT))
        cur_v = array.array("f")
        cur_i = array.array("H")

    for packed in parts:
        if not packed:
            continue
        verts, indices, _fmt = packed
        nv = len(verts) // _FLOATS_PER_VERT
        ni = len(indices)
        if nv <= 0 or ni <= 0:
            continue
        if nv > MAX_KIVY_MESH_VERTS or ni > MAX_KIVY_MESH_INDICES:
            flush()
            out.extend(_split_indexed_mesh(verts, indices))
            continue
        base = len(cur_v) // _FLOATS_PER_VERT
        base_i = len(cur_i)
        if base and (base + nv > MAX_KIVY_MESH_VERTS or base_i + ni > MAX_KIVY_MESH_INDICES):
            flush()
            base = 0
        cur_v.extend(verts)
        if base == 0:
            cur_i.extend(indices)
        else:
            shifted = np.frombuffer(memoryview(indices), dtype=np.uint16).astype(np.uint32)
            shifted += np.uint32(base)
            cur_i.frombytes(shifted.astype(np.uint16).tobytes())
    flush()
    return out


def keyed_packed_meshes(
    packed: list[PackedMesh] | None,
) -> dict[TileKey, tuple | None]:
    """Map packed draws to ``(i, 0, 0)`` keys for the viewer replace path."""
    if not packed:
        return {(0, 0, 0): None}
    return {(i, 0, 0): item for i, item in enumerate(packed)}
