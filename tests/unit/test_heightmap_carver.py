"""Unit tests for the Z-heightmap stock carver."""

from __future__ import annotations

import numpy as np

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
    tile_keys_from_window_mask,
)
from carveracontroller.addons.stock.simulator.carvers.heightmap import HeightmapBackend
from carveracontroller.addons.stock.simulator.carvers.heightmap.backend import (
    _sample_profile_z_for_radius,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RectangularStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType


def _flat_tool(diameter: float = 4.0) -> ToolDefinition:
    return ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=diameter,
        flute_length=10.0,
        length=40.0,
    )


def _vbit() -> ToolDefinition:
    return ToolDefinition(
        number=1,
        tool_type=ToolType.CHAMFER_MILL,
        diameter=6.0,
        tip_diameter=0.2,
        taper_angle_deg=15.0,
        flute_length=10.0,
        length=40.0,
    )


def test_heightmap_seeds_rectangular_top():
    bounds = StockBounds(0, 0, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(10, 10, 5))
    assert hm.height_at_world(5.0, 5.0) == 5.0
    assert hm.hud_stats()["carver"] == "heightmap"


def test_heightmap_seeds_standing_cylinder():
    bounds = StockBounds(0, 0, 0, 10, 10, 8)
    hm = HeightmapBackend(bounds, 1.0, CylindricalStock(diameter_mm=10.0, height_mm=8.0))
    assert hm.height_at_world(5.0, 5.0) == 8.0
    # Corner outside circle
    assert hm.height_at_world(0.5, 0.5) is None


def test_heightmap_flat_pocket_floor():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    tool = _flat_tool(4.0)
    dirty = hm.carve_segment((-3.0, 0.0, 2.0), (3.0, 0.0, 2.0), tool)
    assert dirty
    h = hm.height_at_world(0.0, 0.0)
    assert h is not None
    assert h <= 2.0 + 1e-3
    # Outside tool radius untouched
    outer = hm.height_at_world(0.0, 8.0)
    assert outer is not None and abs(outer - 5.0) < 1e-3


def test_heightmap_vbit_clears_center_deeper_than_edge():
    bounds = StockBounds(-8, -8, 0, 8, 8, 6)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(16, 16, 6))
    tool = _vbit()
    hm.carve_segment((0.0, 0.0, 3.0), (0.0, 0.0, 3.0), tool)
    center = hm.height_at_world(0.0, 0.0)
    edge = hm.height_at_world(1.5, 0.0)
    assert center is not None and edge is not None
    # Tip is thinner: center should be cut to tip Z; further out higher or uncut.
    assert center <= edge + 1e-6


def test_heightmap_mesh_tiles_nonzero():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4))
    keys = hm.initial_surface_keys()
    meshes = hm.mesh_tiles(keys)
    assert list(meshes) == [(0, 0, 0)]
    assert any(v is not None for v in meshes.values())


def test_heightmap_uncut_mesh_merges_cells():
    bounds = StockBounds(0, 0, 0, 32, 32, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(32, 32, 4))
    meshes = hm.mesh_tiles(hm.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    # Naive: 32x32 tops × 4 verts = 4096 before skirts. Uniform tiles stay a handful.
    assert n_verts < 4096 / 4


def test_heightmap_mesh_tiles_are_per_tile():
    bounds = StockBounds(0, 0, 0, 32, 32, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(32, 32, 4))
    keys = {(0, 0, 0), (1, 0, 0)}
    meshes = hm.mesh_tiles(keys)
    assert (0, 0, 0) in meshes and (1, 0, 0) in meshes
    assert (0, 1, 0) not in meshes


def test_heightmap_varied_field_one_top_per_cell():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4))
    hm.heights[:, :] = 2.0 + np.arange(64, dtype=np.float32).reshape(8, 8) * 0.01
    meshes = hm.mesh_tiles(hm.initial_surface_keys())
    n_top = 0
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        n_top += int(np.sum(verts[:, 5] > 0.5))
    assert n_top == 8 * 8 * 4


def test_heightmap_checkpoint_roundtrip():
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.carve_segment((-3.0, 0.0, 2.0), (3.0, 0.0, 2.0), _flat_tool(4.0))
    payload = hm.snapshot_full()
    hm2 = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm2.restore(payload)
    assert hm2.height_at_world(0.0, 0.0) == hm.height_at_world(0.0, 0.0)
    assert hm2.height_at_world(0.0, 8.0) == hm.height_at_world(0.0, 8.0)


def test_heightmap_mesh_has_bottom_faces():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4))
    meshes = hm.mesh_tiles(hm.initial_surface_keys())
    rows = []
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        rows.append(verts[:, 3:6])
    nrm = np.concatenate(rows, axis=0)
    assert np.any(nrm[:, 2] > 0.5)
    assert np.any(nrm[:, 2] < -0.5)


def test_heightmap_copy_tiles_meshes_window():
    bounds = StockBounds(0, 0, 0, 32, 32, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(32, 32, 4))
    keys = {(0, 0, 0), (1, 0, 0)}
    copied = hm.copy_tiles(keys)
    meshes = copied.mesh_tiles(keys)
    assert any(v is not None for v in meshes.values())


def test_heightmap_flat_pocket_merges_floor_quads():
    """A constant-depth pocket should not emit one top quad per cell."""
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.carve_segment((-3.0, 0.0, 2.0), (3.0, 0.0, 2.0), _flat_tool(4.0))
    meshes = hm.mesh_tiles(hm.expand_dirty(hm.all_non_full_keys()))
    n_top = 0
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        n_top += int(np.sum(verts[:, 5] > 0.5))
    # Window is several tiles; a naive floor is hundreds of cell quads.
    assert n_top < 64 * 4


def test_tile_keys_from_window_mask_matches_unique():
    rng = np.random.default_rng(0)
    mask = rng.random((37, 29)) > 0.7
    mask[0, 0] = True
    got = tile_keys_from_window_mask(mask, 5, 9, 16)
    ii, jj = np.nonzero(mask)
    expect = {(int((i + 5) // 16), int((j + 9) // 16), 0) for i, j in zip(ii, jj)}
    assert got == expect
    assert tile_keys_from_window_mask(np.zeros((8, 8), dtype=bool), 0, 0, 16) == set()


def test_sample_profile_z_matches_segment_inverse():
    profile = resolve_cutting_profile(_vbit())
    zs = np.array([z for z, _r in profile], dtype=np.float64)
    rs = np.array([r for _z, r in profile], dtype=np.float64)
    dist = np.linspace(0.0, float(np.max(rs)) + 0.5, 64)
    got = _sample_profile_z_for_radius(zs, rs, dist)

    # Smallest Z on any segment where r(z) >= dist (same rule as the carver).
    expect = np.full_like(dist, np.inf)
    for i in range(len(zs) - 1):
        z0, z1 = float(zs[i]), float(zs[i + 1])
        r0, r1 = float(rs[i]), float(rs[i + 1])
        cand = np.full_like(dist, np.inf)
        at_start = dist <= r0 + 1e-9
        cand[at_start] = z0
        if abs(r1 - r0) >= 1e-12:
            crosses = (~at_start) & (dist <= r1 + 1e-9)
            t = np.clip((dist[crosses] - r0) / (r1 - r0), 0.0, 1.0)
            cand[crosses] = z0 + t * (z1 - z0)
        expect = np.minimum(expect, cand)
    for z, r in zip(zs, rs):
        expect = np.minimum(expect, np.where(dist <= float(r) + 1e-9, float(z), np.inf))
    finite = np.isfinite(expect)
    assert np.all(np.isfinite(got) == finite)
    assert np.allclose(got[finite], expect[finite], atol=1e-9)


def test_sample_profile_z_undercut_uses_smallest_z():
    zs = np.array([0.0, 1.0, 2.0], dtype=np.float64)
    rs = np.array([2.0, 0.5, 2.0], dtype=np.float64)
    dist = np.array([1.5, 0.4, 2.5])
    got = _sample_profile_z_for_radius(zs, rs, dist)
    assert got[0] == 0.0
    assert got[1] == 0.0
    assert np.isinf(got[2])


def test_pack_quad_meshes_splits_under_kivy_uint16_limit():
    """Kivy Mesh indices are unsigned short; coalesced fields must chunk."""
    import numpy as np

    from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
        MAX_KIVY_MESH_VERTS,
        keyed_packed_meshes,
        pack_quad_meshes,
    )

    n_quads = (MAX_KIVY_MESH_VERTS // 4) + 8
    corners = np.zeros((n_quads, 4, 3), dtype=np.float32)
    normals = np.zeros((n_quads, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    chunks = pack_quad_meshes(corners, normals, (1.0, 1.0, 1.0, 1.0))
    assert len(chunks) == 2
    meshes = keyed_packed_meshes(chunks)
    assert (0, 0, 0) in meshes and (1, 0, 0) in meshes
    for verts, idx, _fmt in chunks:
        assert len(verts) // 12 <= MAX_KIVY_MESH_VERTS
        assert max(idx) <= 65535


def test_heightmap_ramp_clears_uphill_footprint():
    """Descending ramp must min remaining Z over covering poses, not XY-closest."""
    bounds = StockBounds(0, 0, 0, 20, 10, 10)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(20, 10, 10))
    tool = _flat_tool(6.0)
    # 1:1 ramp; R=3 mm so the low pose still covers the start cell.
    hm.carve_segment((0.5, 0.5, 5.0), (3.5, 0.5, 2.0), tool)
    h = hm.height_at_world(0.5, 0.5)
    assert h is not None
    # Closest-pose logic leaves start Z (5). Correct floor is the low covering tip.
    assert h <= 2.0 + 1e-3
    untouched = hm.height_at_world(0.5, 8.5)
    assert untouched is not None and abs(untouched - 10.0) < 1e-3


def test_heightmap_ramp_clears_off_centerline_to_lowest_covering_pose():
    """Cells beside a descending ramp must use the low covering tip, not XY-closest.

    Reconstructing the coverage-circle hypot can land 1 ULP outside the tool
    radius and drop the endpoint sample, leaving a high/low sawtooth across
    the kerf (Makera-style 2D-contour tabs).
    """
    bounds = StockBounds(0, 0, 0, 20, 10, 10)
    hm = HeightmapBackend(bounds, 0.1, RectangularStock(20, 10, 10))
    tool = _flat_tool(6.0)
    hm.carve_segment((0.5, 5.0, 5.0), (10.5, 5.0, 0.0), tool)
    h = hm.height_at_world(0.5, 6.5)
    assert h is not None
    # dist_perp=1.5, R=3 → covering half-width ≈ 2.598 mm along a 10 mm, ΔZ=-5 ramp.
    # Lowest covering Z ≈ 5 - 5 * 2.598/10 ≈ 3.70. Closest-pose Z is 5.0.
    assert h <= 3.75


def test_heightmap_flat_tab_ramp_is_not_crenellated():
    """A 2D-contour tab (ramp up then down) must not alternate high/low across the slot."""
    bounds = StockBounds(0, 0, -2, 30, 12, 0)
    hm = HeightmapBackend(bounds, 0.1, RectangularStock(30, 12, 2))
    tool = _flat_tool(3.175)
    y = 6.0
    hm.carve_segment((2.0, y, -0.5), (28.0, y, -0.5), tool)
    hm.carve_segment((2.0, y, -1.5), (10.0, y, -1.5), tool)
    hm.carve_segment((10.0, y, -1.5), (15.0, y, -0.5), tool)
    hm.carve_segment((15.0, y, -0.5), (20.0, y, -1.5), tool)
    hm.carve_segment((20.0, y, -1.5), (28.0, y, -1.5), tool)

    ys = np.arange(y - 1.7, y + 1.7 + 1e-9, 0.1)
    hs = np.array([hm.height_at_world(15.0, float(yy)) for yy in ys], dtype=np.float64)
    cut = hs < -0.05
    assert cut.any()
    vals = hs[cut]
    # Interior local maxima: a U-groove is fine; every-other-cell teeth are not.
    if vals.size >= 3:
        interior = vals[1:-1]
        maxima = (interior > vals[:-2] + 0.08) & (interior > vals[2:] + 0.08)
        assert int(np.sum(maxima)) <= 2


def _packed_vertex_rows(meshes: dict) -> np.ndarray:
    rows = []
    for packed in meshes.values():
        if not packed:
            continue
        rows.append(np.asarray(packed[0], dtype=np.float32).reshape(-1, 12))
    assert rows
    return np.concatenate(rows, axis=0)


def test_heightmap_through_cut_clamps_to_min_z():
    """CAM overshoot past stock bottom must not invert exterior mesh skirts."""
    bounds = StockBounds(-10, -10, 0, 10, 10, 5)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.carve_segment((-3.0, 0.0, -0.1), (3.0, 0.0, -0.1), _flat_tool(4.0))
    h = hm.height_at_world(0.0, 0.0)
    assert h is not None
    assert h >= bounds.min_z - 1e-6
    assert h <= bounds.min_z + 1e-3
    valid = hm.heights > -1e20
    assert np.all(hm.heights[valid] >= bounds.min_z - 1e-6)

    meshes = hm.mesh_tiles(hm.expand_dirty(hm.all_non_full_keys()))
    verts = _packed_vertex_rows(meshes)
    assert np.all(verts[:, 2] >= bounds.min_z - 1e-4)
    # Zero-thickness cells must not keep a +Z floor film.
    at_floor = verts[:, 2] <= bounds.min_z + 1e-3
    facing_up = verts[:, 5] > 0.5
    assert not np.any(at_floor & facing_up)
    # Uncut stock around the slot still has a top; hole walls still exist.
    assert np.any((verts[:, 5] > 0.5) & (verts[:, 2] >= bounds.max_z - 1e-3))
    assert np.any(np.abs(verts[:, 5]) < 0.5)


def test_heightmap_through_cut_top_origin_opens_hole():
    """Z=0 on top of 5 mm stock: overshoot past Z=-5 must punch through."""
    bounds = StockBounds(-10, -10, -5, 10, 10, 0)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(20, 20, 5))
    hm.carve_segment((-3.0, 0.0, -5.3), (3.0, 0.0, -5.3), _flat_tool(4.0))
    h = hm.height_at_world(0.0, 0.0)
    assert h is not None and h <= bounds.min_z + 1e-3

    meshes = hm.mesh_tiles(hm.expand_dirty(hm.all_non_full_keys()))
    verts = _packed_vertex_rows(meshes)
    at_floor = verts[:, 2] <= bounds.min_z + 1e-3
    facing_up = verts[:, 5] > 0.5
    assert not np.any(at_floor & facing_up)


def test_heightmap_full_tile_through_cut_has_no_top():
    """Uniform-tile fast path must not emit a min_z film over a cleared tile."""
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4), tile_size=16)
    hm.carve_segment((4.0, 4.0, -0.5), (4.0, 4.0, -0.5), _flat_tool(20.0))
    assert np.all(hm.heights <= bounds.min_z + 1e-3)
    meshes = hm.mesh_tiles(hm.initial_surface_keys())
    assert all(v is None for v in meshes.values())
