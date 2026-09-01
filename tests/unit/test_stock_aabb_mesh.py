"""Unit tests for stock AABB mesh builders."""

import math

import pytest

from carveracontroller.addons.stock.stock_aabb_mesh import (
    DEFAULT_CYLINDER_SEGMENTS,
    FLOATS_PER_VERTEX,
    STOCK_EDGE_COLOR,
    STOCK_FILL_COLOR,
    STOCK_VERTEX_FORMAT,
    build_box_edges,
    build_box_triangles,
    build_cylinder_edges,
    build_cylinder_triangles,
    build_x_cylinder_edges,
    build_x_cylinder_triangles,
)


def test_vertex_format_matches_stride():
    assert sum(item[1] for item in STOCK_VERTEX_FORMAT) == FLOATS_PER_VERTEX


def test_build_box_triangles_counts_and_color():
    color = STOCK_FILL_COLOR
    vertices, indices = build_box_triangles(0, 0, 0, 10, 20, 5, color)
    # 6 faces × 4 verts × 10 floats
    assert len(vertices) == 6 * 4 * FLOATS_PER_VERTEX
    # 6 faces × 2 triangles × 3 indices
    assert len(indices) == 6 * 2 * 3
    # Color floats are the last 4 of each vertex
    for i in range(0, len(vertices), FLOATS_PER_VERTEX):
        assert tuple(vertices[i + 6 : i + 10]) == color
    # Corners span the requested AABB
    xs = vertices[0::FLOATS_PER_VERTEX]
    ys = vertices[1::FLOATS_PER_VERTEX]
    zs = vertices[2::FLOATS_PER_VERTEX]
    assert min(xs) == 0 and max(xs) == 10
    assert min(ys) == 0 and max(ys) == 20
    assert min(zs) == 0 and max(zs) == 5


def test_build_box_triangles_top_color_only_on_plus_z():
    fill = (0.1, 0.2, 0.3, 0.4)
    top = (0.9, 0.8, 0.7, 0.6)
    vertices, _indices = build_box_triangles(0, 0, 0, 10, 20, 5, fill, top_color=top)
    # First face is +Z (4 verts), remaining 5 faces use fill.
    for i in range(4):
        offset = i * FLOATS_PER_VERTEX
        assert tuple(vertices[offset + 6 : offset + 10]) == top
        assert vertices[offset + 5] == 1.0
    for i in range(4, 24):
        offset = i * FLOATS_PER_VERTEX
        assert tuple(vertices[offset + 6 : offset + 10]) == fill


def test_build_box_edges_counts_and_color():
    color = STOCK_EDGE_COLOR
    vertices, indices = build_box_edges(-1, -2, -3, 1, 2, 3, color)
    # 8 corners × 10 floats
    assert len(vertices) == 8 * FLOATS_PER_VERTEX
    # 12 edges × 2 indices
    assert len(indices) == 12 * 2
    for i in range(0, len(vertices), FLOATS_PER_VERTEX):
        assert tuple(vertices[i + 6 : i + 10]) == color
    assert max(indices) == 7


def test_build_cylinder_triangles_counts_and_extent():
    color = STOCK_FILL_COLOR
    segs = DEFAULT_CYLINDER_SEGMENTS
    vertices, indices = build_cylinder_triangles(0, 0, -5, 5, 10, color, segments=segs)
    # side (2*segs) + bottom (1+segs) + top (1+segs)
    assert len(vertices) == (2 * segs + 2 * (1 + segs)) * FLOATS_PER_VERTEX
    assert len(indices) == (segs * 2 + segs + segs) * 3
    assert all(math.isfinite(v) for v in vertices)
    for i in range(0, len(vertices), FLOATS_PER_VERTEX):
        assert tuple(vertices[i + 6 : i + 10]) == color
    xs = vertices[0::FLOATS_PER_VERTEX]
    ys = vertices[1::FLOATS_PER_VERTEX]
    zs = vertices[2::FLOATS_PER_VERTEX]
    assert min(xs) == pytest.approx(-10)
    assert max(xs) == pytest.approx(10)
    assert min(ys) == pytest.approx(-10)
    assert max(ys) == pytest.approx(10)
    assert min(zs) == -5 and max(zs) == 5


def test_build_cylinder_triangles_top_color_on_plus_z_cap():
    fill = (0.1, 0.2, 0.3, 0.4)
    top = (0.9, 0.8, 0.7, 0.6)
    segs = 8
    vertices, _indices = build_cylinder_triangles(0, 0, -5, 5, 10, fill, segments=segs, top_color=top)
    # side (2*segs) + bottom (1+segs) + top (1+segs)
    top_start = 2 * segs + 1 + segs
    for i in range(top_start):
        offset = i * FLOATS_PER_VERTEX
        assert tuple(vertices[offset + 6 : offset + 10]) == fill
    for i in range(top_start, len(vertices) // FLOATS_PER_VERTEX):
        offset = i * FLOATS_PER_VERTEX
        assert tuple(vertices[offset + 6 : offset + 10]) == top


def test_build_cylinder_edges_counts_and_color():
    color = STOCK_EDGE_COLOR
    segs = 12
    verticals = 4
    vertices, indices = build_cylinder_edges(1, 2, 0, 8, 5, color, segments=segs, verticals=verticals)
    assert len(vertices) == 2 * segs * FLOATS_PER_VERTEX
    # 2 rings + verticals
    assert len(indices) == (2 * segs + verticals) * 2
    assert all(math.isfinite(v) for v in vertices)
    for i in range(0, len(vertices), FLOATS_PER_VERTEX):
        assert tuple(vertices[i + 6 : i + 10]) == color


def test_build_x_cylinder_triangles_counts_and_extent():
    color = STOCK_FILL_COLOR
    segs = DEFAULT_CYLINDER_SEGMENTS
    vertices, indices = build_x_cylinder_triangles(0, 0, -5, 5, 10, color, segments=segs)
    assert len(vertices) == (2 * segs + 2 * (1 + segs)) * FLOATS_PER_VERTEX
    assert len(indices) == (segs * 2 + segs + segs) * 3
    xs = vertices[0::FLOATS_PER_VERTEX]
    ys = vertices[1::FLOATS_PER_VERTEX]
    zs = vertices[2::FLOATS_PER_VERTEX]
    assert min(xs) == -5 and max(xs) == 5
    assert min(ys) == pytest.approx(-10)
    assert max(ys) == pytest.approx(10)
    assert min(zs) == pytest.approx(-10)
    assert max(zs) == pytest.approx(10)


def test_build_x_cylinder_triangles_top_color_on_barrel():
    fill = (0.1, 0.2, 0.3, 0.4)
    top = (0.9, 0.8, 0.7, 0.6)
    segs = 8
    vertices, _indices = build_x_cylinder_triangles(0, 0, -5, 5, 10, fill, segments=segs, top_color=top)
    barrel_verts = 2 * segs
    for i in range(barrel_verts):
        offset = i * FLOATS_PER_VERTEX
        assert tuple(vertices[offset + 6 : offset + 10]) == top
    for i in range(barrel_verts, len(vertices) // FLOATS_PER_VERTEX):
        offset = i * FLOATS_PER_VERTEX
        assert tuple(vertices[offset + 6 : offset + 10]) == fill


def test_build_x_cylinder_edges_counts_and_color():
    color = STOCK_EDGE_COLOR
    segs = 12
    verticals = 4
    vertices, indices = build_x_cylinder_edges(1, 2, 0, 8, 5, color, segments=segs, verticals=verticals)
    assert len(vertices) == 2 * segs * FLOATS_PER_VERTEX
    assert len(indices) == (2 * segs + verticals) * 2
    for i in range(0, len(vertices), FLOATS_PER_VERTEX):
        assert tuple(vertices[i + 6 : i + 10]) == color
