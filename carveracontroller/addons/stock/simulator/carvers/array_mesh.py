"""Shared mesh packing and tile-key helpers for dense array carvers."""

from __future__ import annotations

import array
import zlib

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.backend import TileKey
from carveracontroller.addons.stock.simulator.mesh_format import VERTEX_FORMAT

_FLOATS_PER_VERT = 12
# Kivy Mesh indices are unsigned short; stay under 65536 vertices per draw.
MAX_KIVY_MESH_VERTS = 65500
_MAX_QUADS_PER_MESH = MAX_KIVY_MESH_VERTS // 4

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


def quad_normals(corners: np.ndarray) -> np.ndarray:
    """Unit normals from ``(N, 4, 3)`` quads using edges 0→1 and 0→3."""
    e1 = corners[:, 1] - corners[:, 0]
    e2 = corners[:, 3] - corners[:, 0]
    n = np.cross(e1, e2)
    lens = np.linalg.norm(n, axis=1, keepdims=True)
    return (n / np.maximum(lens, 1e-12)).astype(np.float32)


def pick_outward_quads(
    p00: np.ndarray,
    p10: np.ndarray,
    p11: np.ndarray,
    p01: np.ndarray,
    hint: np.ndarray,
) -> np.ndarray:
    """Pack ``(N, 4, 3)`` quads, choosing the diagonal whose triangles face ``hint``.

    Kivy triangulates ``(0,1,2)`` and ``(0,2,3)``. On a sloped cylindrical graph the
    two diagonals are not equivalent: the wrong one folds a triangle inward and
    back-face culling punches a hole.
    """
    n = int(p00.shape[0])
    if n == 0:
        return np.empty((0, 4, 3), dtype=np.float32)

    def _tri_n(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
        return np.cross(b - a, c - a)

    n_a1 = _tri_n(p00, p10, p11)
    n_a2 = _tri_n(p00, p11, p01)
    n_b1 = _tri_n(p10, p11, p01)
    n_b2 = _tri_n(p10, p01, p00)
    score_a = np.minimum((n_a1 * hint).sum(axis=1), (n_a2 * hint).sum(axis=1))
    score_b = np.minimum((n_b1 * hint).sum(axis=1), (n_b2 * hint).sum(axis=1))
    use_b = score_b > score_a
    shell = np.empty((n, 4, 3), dtype=np.float32)
    wb = use_b[:, None]
    shell[:, 0] = np.where(wb, p10, p00)
    shell[:, 1] = np.where(wb, p11, p10)
    shell[:, 2] = np.where(wb, p01, p11)
    shell[:, 3] = np.where(wb, p00, p01)
    return shell


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
    """Pack quads into one or more Kivy-safe meshes (uint16 index limit)."""
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


def keyed_packed_meshes(
    packed: list[PackedMesh] | None,
) -> dict[TileKey, tuple | None]:
    """Map packed draws to ``(i, 0, 0)`` keys for the viewer replace path."""
    if not packed:
        return {(0, 0, 0): None}
    return {(i, 0, 0): item for i, item in enumerate(packed)}
