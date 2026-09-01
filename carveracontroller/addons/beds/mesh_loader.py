"""Load bed OBJ meshes into Kivy-ready interleaved arrays."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

BED_VERTEX_FORMAT = [
    (b"v_pos", 3, "float"),
    (b"v_normal", 3, "float"),
    (b"v_color", 4, "float"),
]

FLOATS_PER_VERTEX = 10

# Kivy Mesh uses unsigned short index values *and* a 65535-long index list.
# Catalog OBJs stay compact (welded), but GPU packing expands each triangle so
# hole rims are not smooth-shaded into the top face. That makes SMW draws
# exceed both caps, so we split into several Mesh instructions.
KIVY_MESH_MAX_VERTICES = 65535
KIVY_MESH_MAX_INDICES = 65535


@dataclass
class BedMeshData:
    """Model-local millimetre mesh (origin at front-left top)."""

    positions: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    indices: list[int]
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    thickness_mm: float


def read_obj_metadata(path: str) -> dict[str, float | tuple[float, float, float]]:
    """Parse leading OBJ comments for bbox / thickness (no mesh load)."""
    meta: dict[str, float | tuple[float, float, float]] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                if not stripped.startswith("#"):
                    break
                parts = stripped[1:].split()
                if not parts:
                    continue
                key = parts[0].lower()
                nums = []
                for token in parts[1:]:
                    try:
                        nums.append(float(token))
                    except ValueError:
                        nums = []
                        break
                if key == "thickness_mm" and len(nums) == 1:
                    meta["thickness_mm"] = nums[0]
                elif key == "bbox_min" and len(nums) == 3:
                    meta["bbox_min"] = (nums[0], nums[1], nums[2])
                elif key == "bbox_max" and len(nums) == 3:
                    meta["bbox_max"] = (nums[0], nums[1], nums[2])
    except OSError:
        return {}
    return meta


def _face_normal_unnormalized(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)


def _fill_missing_normals(
    positions: list[tuple[float, float, float]],
    normals: list[tuple[float, float, float]],
    indices: list[int],
) -> None:
    """Area-weighted vertex normals for corners that had no OBJ ``vn``."""
    need = [(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) < 1e-12 for n in normals]
    if not any(need):
        return
    acc = [[0.0, 0.0, 0.0] for _ in positions]
    for t in range(0, len(indices) - 2, 3):
        i0, i1, i2 = indices[t], indices[t + 1], indices[t + 2]
        nx, ny, nz = _face_normal_unnormalized(positions[i0], positions[i1], positions[i2])
        for i in (i0, i1, i2):
            if need[i]:
                acc[i][0] += nx
                acc[i][1] += ny
                acc[i][2] += nz
    for i, missing in enumerate(need):
        if not missing:
            continue
        ax, ay, az = acc[i]
        length = math.sqrt(ax * ax + ay * ay + az * az)
        if length <= 1e-12:
            normals[i] = (0.0, 0.0, 1.0)
        else:
            normals[i] = (ax / length, ay / length, az / length)


def _aabb(positions: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _obj_index(raw: int, count: int) -> int:
    if raw < 0:
        return count + raw
    return raw - 1


def _parse_face_corner(token: str) -> tuple[int, int]:
    """Return 1-based (vertex, normal) indices; missing normal is 0."""
    parts = token.split("/")
    v = int(parts[0])
    n = int(parts[2]) if len(parts) >= 3 and parts[2] else 0
    return v, n


def _load_obj_indexed(
    path: str,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[int]]:
    """Parse a Wavefront OBJ keeping shared vertices (not one copy per corner)."""
    raw_v: list[tuple[float, float, float]] = []
    raw_n: list[tuple[float, float, float]] = []
    faces: list[list[tuple[int, int]]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line or line[0] == "#" or line[0] == "s":
                continue
            values = line.split()
            if not values:
                continue
            kind = values[0]
            if kind == "v" and len(values) >= 4:
                raw_v.append((float(values[1]), float(values[2]), float(values[3])))
            elif kind == "vn" and len(values) >= 4:
                raw_n.append((float(values[1]), float(values[2]), float(values[3])))
            elif kind == "f" and len(values) >= 4:
                faces.append([_parse_face_corner(tok) for tok in values[1:]])

    if len(raw_v) < 3 or not faces:
        raise ValueError(f"empty mesh in {path}")

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []
    uniqued: dict[tuple[int, int], int] = {}
    ncount = len(raw_n)
    vcount = len(raw_v)

    def emit_corner(v_raw: int, n_raw: int) -> int:
        v_i = _obj_index(v_raw, vcount)
        n_i = _obj_index(n_raw, ncount) if n_raw else -1
        if v_i < 0 or v_i >= vcount:
            raise ValueError(f"vertex index out of range in {path}")
        key = (v_i, n_i)
        existing = uniqued.get(key)
        if existing is not None:
            return existing
        nrm = raw_n[n_i] if 0 <= n_i < ncount else (0.0, 0.0, 0.0)
        out = len(positions)
        uniqued[key] = out
        positions.append(raw_v[v_i])
        normals.append(nrm)
        return out

    for face in faces:
        if len(face) < 3:
            continue
        corners = [emit_corner(v_raw, n_raw) for v_raw, n_raw in face]
        for t in range(1, len(corners) - 1):
            indices.extend((corners[0], corners[t], corners[t + 1]))

    if len(positions) < 3 or not indices:
        raise ValueError(f"empty mesh in {path}")

    _fill_missing_normals(positions, normals, indices)
    return positions, normals, indices


_MESH_CACHE: dict[str, BedMeshData] = {}


def load_bed_mesh(path: str) -> BedMeshData:
    """Load an OBJ (catalog or custom) into model-local millimetre arrays."""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(path)
    cache_key = os.path.abspath(path)
    cached = _MESH_CACHE.get(cache_key)
    if cached is not None:
        try:
            mtime = os.path.getmtime(cache_key)
        except OSError:
            mtime = -1.0
        if getattr(cached, "_mtime", None) == mtime:
            return cached

    positions, normals, indices = _load_obj_indexed(path)
    meta = read_obj_metadata(path)
    bbox_min = meta.get("bbox_min")
    bbox_max = meta.get("bbox_max")
    if not (isinstance(bbox_min, tuple) and isinstance(bbox_max, tuple)):
        bbox_min, bbox_max = _aabb(positions)
    thickness = meta.get("thickness_mm")
    if not isinstance(thickness, (int, float)):
        thickness = float(bbox_max[2] - bbox_min[2])

    data = BedMeshData(
        positions=positions,
        normals=normals,
        indices=list(indices),
        bbox_min=(float(bbox_min[0]), float(bbox_min[1]), float(bbox_min[2])),
        bbox_max=(float(bbox_max[0]), float(bbox_max[1]), float(bbox_max[2])),
        thickness_mm=abs(float(thickness)),
    )
    try:
        data._mtime = os.path.getmtime(cache_key)  # type: ignore[attr-defined]
    except OSError:
        data._mtime = -1.0  # type: ignore[attr-defined]
    _MESH_CACHE[cache_key] = data
    return data


def _normalized_face_normal(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
) -> tuple[float, float, float]:
    nx, ny, nz = _face_normal_unnormalized(p0, p1, p2)
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _pack_vertex(
    pos: tuple[float, float, float],
    nrm: tuple[float, float, float],
    scale: float,
    albedo_rgb: tuple[float, float, float],
) -> tuple[float, ...]:
    s = float(scale)
    cr, cg, cb = float(albedo_rgb[0]), float(albedo_rgb[1]), float(albedo_rgb[2])
    return (pos[0] * s, pos[1] * s, pos[2] * s, nrm[0], nrm[1], nrm[2], cr, cg, cb, 1.0)


def _pack_triangle(
    mesh: BedMeshData,
    i0: int,
    i1: int,
    i2: int,
    scale: float,
    albedo_rgb: tuple[float, float, float],
) -> list[float]:
    """Three GPU vertices with the triangle's face normal (no smooth weld)."""
    p0 = mesh.positions[i0]
    p1 = mesh.positions[i1]
    p2 = mesh.positions[i2]
    nrm = _normalized_face_normal(p0, p1, p2)
    packed: list[float] = []
    for pos in (p0, p1, p2):
        packed.extend(_pack_vertex(pos, nrm, scale, albedo_rgb))
    return packed


def pack_bed_vertices(
    mesh: BedMeshData,
    scale: float,
    albedo_rgb: tuple[float, float, float],
) -> tuple[list[float], list[int]]:
    """Interleave scaled positions, face normals, and albedo into ``BED_VERTEX_FORMAT``.

    Each triangle is expanded to three vertices so welded hole-rim corners keep
    a flat top-face normal instead of averaging with the hole wall.
    """
    vertices: list[float] = []
    indices: list[int] = []
    for t in range(0, len(mesh.indices) - 2, 3):
        base = len(indices)
        vertices.extend(
            _pack_triangle(mesh, mesh.indices[t], mesh.indices[t + 1], mesh.indices[t + 2], scale, albedo_rgb)
        )
        indices.extend((base, base + 1, base + 2))
    return vertices, indices


def pack_bed_mesh_chunks(
    mesh: BedMeshData,
    scale: float,
    albedo_rgb: tuple[float, float, float],
    max_vertices: int = KIVY_MESH_MAX_VERTICES,
    max_indices: int = KIVY_MESH_MAX_INDICES,
) -> list[tuple[list[float], list[int]]]:
    """Pack into one or more Kivy meshes that fit uint16 vertices *and* indices."""
    limit_v = max(3, int(max_vertices))
    limit_i = max(3, int(max_indices))
    limit = min(limit_v, limit_i)
    limit -= limit % 3
    if len(mesh.indices) <= limit:
        return [pack_bed_vertices(mesh, scale, albedo_rgb)]

    chunks: list[tuple[list[float], list[int]]] = []
    vertices: list[float] = []
    indices: list[int] = []

    def flush() -> None:
        nonlocal vertices, indices
        if indices:
            chunks.append((vertices, indices))
        vertices = []
        indices = []

    for t in range(0, len(mesh.indices) - 2, 3):
        if indices and (len(indices) + 3) > limit:
            flush()
        base = len(indices)
        vertices.extend(
            _pack_triangle(mesh, mesh.indices[t], mesh.indices[t + 1], mesh.indices[t + 2], scale, albedo_rgb)
        )
        indices.extend((base, base + 1, base + 2))
    flush()
    return chunks


def clear_mesh_cache() -> None:
    _MESH_CACHE.clear()
