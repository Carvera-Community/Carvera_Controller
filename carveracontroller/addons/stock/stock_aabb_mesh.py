"""Procedural stock mesh builders for preview (fill + wireframe edges)."""

from __future__ import annotations

import math

STOCK_FILL_COLOR = (0.72, 0.68, 0.48, 0.28)
STOCK_EDGE_COLOR = (0.95, 0.90, 0.55, 0.90)
STOCK_VERTEX_FORMAT = [
    (b"v_pos", 3, "float"),
    (b"v_normal", 3, "float"),
    (b"v_color", 4, "float"),
]

# pos(3) + normal(3) + color(4)
FLOATS_PER_VERTEX = 10

DEFAULT_CYLINDER_SEGMENTS = 48


def build_box_triangles(x0, y0, z0, x1, y1, z1, color, top_color=None):
    """Return (vertices, indices) for a solid AABB with per-face normals.

    *top_color* tints the +Z face; other faces keep *color*.
    """
    skin = top_color if top_color is not None else color
    # 6 faces × 4 verts; each vertex: pos(3)+normal(3)+color(4)
    faces = [
        # +Z
        ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], skin),
        # -Z
        ((0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], color),
        # +Y
        ((0, 1, 0), [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)], color),
        # -Y
        ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], color),
        # +X
        ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], color),
        # -X
        ((-1, 0, 0), [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], color),
    ]
    vertices = []
    indices = []
    for normal, corners, face_color in faces:
        base = len(vertices) // FLOATS_PER_VERTEX
        nx, ny, nz = normal
        cr, cg, cb, ca = face_color
        for x, y, z in corners:
            vertices.extend([x, y, z, nx, ny, nz, cr, cg, cb, ca])
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])
    return vertices, indices


def build_box_edges(x0, y0, z0, x1, y1, z1, color):
    """Return (vertices, indices) for the 12 edges of an AABB as GL_LINES."""
    cr, cg, cb, ca = color
    corners = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    vertices = []
    for x, y, z in corners:
        vertices.extend([x, y, z, 0.0, 0.0, 1.0, cr, cg, cb, ca])
    indices = []
    for a, b in edges:
        indices.extend([a, b])
    return vertices, indices


def build_cylinder_triangles(cx, cy, z0, z1, radius, color, segments: int = DEFAULT_CYLINDER_SEGMENTS, top_color=None):
    """Return (vertices, indices) for a Z-axis cylinder (side + caps).

    *top_color* tints the +Z cap; the wall and bottom keep *color*.
    """
    if segments < 3:
        raise ValueError("segments must be >= 3")
    skin = top_color if top_color is not None else color
    vertices: list[float] = []
    indices: list[int] = []

    def add_vert(x, y, z, nx, ny, nz, rgba):
        cr, cg, cb, ca = rgba
        vertices.extend([x, y, z, nx, ny, nz, cr, cg, cb, ca])

    # Side wall: two rings with outward normals in XY.
    side_base = 0
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        nx = math.cos(ang)
        ny = math.sin(ang)
        x = cx + radius * nx
        y = cy + radius * ny
        add_vert(x, y, z0, nx, ny, 0.0, color)
        add_vert(x, y, z1, nx, ny, 0.0, color)
    for i in range(segments):
        i0 = side_base + 2 * i
        i1 = side_base + 2 * ((i + 1) % segments)
        # bottom0, top0, top1 / bottom0, top1, bottom1
        indices.extend([i0, i0 + 1, i1 + 1, i0, i1 + 1, i1])

    # Bottom cap (normal -Z), fan around center.
    bottom_center = len(vertices) // FLOATS_PER_VERTEX
    add_vert(cx, cy, z0, 0.0, 0.0, -1.0, color)
    bottom_ring = bottom_center + 1
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        add_vert(x, y, z0, 0.0, 0.0, -1.0, color)
    for i in range(segments):
        indices.extend([bottom_center, bottom_ring + ((i + 1) % segments), bottom_ring + i])

    # Top cap (normal +Z).
    top_center = len(vertices) // FLOATS_PER_VERTEX
    add_vert(cx, cy, z1, 0.0, 0.0, 1.0, skin)
    top_ring = top_center + 1
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        add_vert(x, y, z1, 0.0, 0.0, 1.0, skin)
    for i in range(segments):
        indices.extend([top_center, top_ring + i, top_ring + ((i + 1) % segments)])

    return vertices, indices


def build_cylinder_edges(cx, cy, z0, z1, radius, color, segments: int = DEFAULT_CYLINDER_SEGMENTS, verticals: int = 4):
    """Return (vertices, indices) for top/bottom rings and a few vertical edges."""
    if segments < 3:
        raise ValueError("segments must be >= 3")
    cr, cg, cb, ca = color
    vertices: list[float] = []
    indices: list[int] = []

    def add_vert(x, y, z):
        vertices.extend([x, y, z, 0.0, 0.0, 1.0, cr, cg, cb, ca])

    # Bottom ring then top ring.
    for z in (z0, z1):
        for i in range(segments):
            ang = 2.0 * math.pi * i / segments
            add_vert(cx + radius * math.cos(ang), cy + radius * math.sin(ang), z)

    for ring in (0, 1):
        base = ring * segments
        for i in range(segments):
            indices.extend([base + i, base + ((i + 1) % segments)])

    # Verticals at evenly spaced ring vertices.
    n_vert = max(1, min(int(verticals), segments))
    for k in range(n_vert):
        i = (k * segments) // n_vert
        indices.extend([i, segments + i])

    return vertices, indices


def build_x_cylinder_triangles(
    cy, cz, x0, x1, radius, color, segments: int = DEFAULT_CYLINDER_SEGMENTS, top_color=None
):
    """Return (vertices, indices) for an X-axis cylinder (side + caps).

    *top_color* tints the barrel (rotary skin); the end caps keep *color*.
    """
    if segments < 3:
        raise ValueError("segments must be >= 3")
    skin = top_color if top_color is not None else color
    vertices: list[float] = []
    indices: list[int] = []

    def add_vert(x, y, z, nx, ny, nz, rgba):
        cr, cg, cb, ca = rgba
        vertices.extend([x, y, z, nx, ny, nz, cr, cg, cb, ca])

    side_base = 0
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        ny = math.cos(ang)
        nz = math.sin(ang)
        y = cy + radius * ny
        z = cz + radius * nz
        add_vert(x0, y, z, 0.0, ny, nz, skin)
        add_vert(x1, y, z, 0.0, ny, nz, skin)
    for i in range(segments):
        i0 = side_base + 2 * i
        i1 = side_base + 2 * ((i + 1) % segments)
        indices.extend([i0, i0 + 1, i1 + 1, i0, i1 + 1, i1])

    cap0_center = len(vertices) // FLOATS_PER_VERTEX
    add_vert(x0, cy, cz, -1.0, 0.0, 0.0, color)
    cap0_ring = cap0_center + 1
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        y = cy + radius * math.cos(ang)
        z = cz + radius * math.sin(ang)
        add_vert(x0, y, z, -1.0, 0.0, 0.0, color)
    for i in range(segments):
        indices.extend([cap0_center, cap0_ring + ((i + 1) % segments), cap0_ring + i])

    cap1_center = len(vertices) // FLOATS_PER_VERTEX
    add_vert(x1, cy, cz, 1.0, 0.0, 0.0, color)
    cap1_ring = cap1_center + 1
    for i in range(segments):
        ang = 2.0 * math.pi * i / segments
        y = cy + radius * math.cos(ang)
        z = cz + radius * math.sin(ang)
        add_vert(x1, y, z, 1.0, 0.0, 0.0, color)
    for i in range(segments):
        indices.extend([cap1_center, cap1_ring + i, cap1_ring + ((i + 1) % segments)])

    return vertices, indices


def build_x_cylinder_edges(
    cy, cz, x0, x1, radius, color, segments: int = DEFAULT_CYLINDER_SEGMENTS, verticals: int = 4
):
    """Return (vertices, indices) for end rings and a few axial edges."""
    if segments < 3:
        raise ValueError("segments must be >= 3")
    cr, cg, cb, ca = color
    vertices: list[float] = []
    indices: list[int] = []

    def add_vert(x, y, z):
        vertices.extend([x, y, z, 0.0, 0.0, 1.0, cr, cg, cb, ca])

    for x in (x0, x1):
        for i in range(segments):
            ang = 2.0 * math.pi * i / segments
            add_vert(x, cy + radius * math.cos(ang), cz + radius * math.sin(ang))

    for ring in (0, 1):
        base = ring * segments
        for i in range(segments):
            indices.extend([base + i, base + ((i + 1) % segments)])

    n_vert = max(1, min(int(verticals), segments))
    for k in range(n_vert):
        i = (k * segments) // n_vert
        indices.extend([i, segments + i])

    return vertices, indices
