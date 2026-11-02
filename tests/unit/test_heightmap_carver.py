"""Unit tests for the Z-heightmap stock carver."""

from __future__ import annotations

import numpy as np
import pytest

from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
    tile_keys_from_window_mask,
)
from carveracontroller.addons.stock.simulator.carvers.heightmap import HeightmapBackend
from carveracontroller.addons.stock.simulator.native import HAS_NATIVE
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RectangularStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType

pytestmark = pytest.mark.skipif(not HAS_NATIVE, reason="native carve extension is not built")


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


def test_uniform_shell_emit_drops_carved_heightmap_bins():
    """Rewind to the uncut box must tombstone every carved heightmap bin."""
    from carveracontroller.addons.stock.simulator import StockSimulator

    bounds = StockBounds(0, 0, 0, 128, 32, 4)
    received: list[dict] = []
    sim = StockSimulator(on_meshes_ready=lambda meshes: received.append(meshes), mesh_throttle_s=0.05)
    try:
        sim.reset(bounds, cell_size_mm=1.0, enable=True, carver_mode="heightmap")
        sim.stop()
        backend = sim.backend
        assert backend is not None and backend.uniform_shell()
        sim._uniform_shell_gpu = False
        sim._heightmap_part_count[(0, 0)] = 2
        sim._heightmap_part_count[(1, 0)] = 1

        received.clear()
        assert sim._try_mesh_and_emit(backend, {(0, 0, 0)}, sim.generation, replace=False) is True
        assert len(received) == 1
        got = received[0]
        assert got[(0, 0, 0)] is not None
        assert got[(0, 0, 1)] is None
        assert got[(1, 0, 0)] is None
        assert sim._heightmap_part_count == {(0, 0): 1}
        assert sim._uniform_shell_gpu is True
    finally:
        sim.stop()


def test_heightmap_mesh_tiles_follow_spatial_bins():
    """Carved stock is one mesh per bin, not one mesh per 16-cell tile."""
    bounds = StockBounds(0, 0, 0, 128, 32, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(128, 32, 4))
    hm.heights[0, 0] = np.float32(1.0)
    # Tile 4 starts at cell 64, the next 64-cell bin.
    keys = {(0, 0, 0), (4, 0, 0)}
    meshes = hm.mesh_tiles(keys)
    assert (0, 0, 0) in meshes and (1, 0, 0) in meshes
    assert (0, 1, 0) not in meshes


def test_heightmap_flat_steps_share_corners():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4))
    hm.heights[:, :] = np.float32(4.0)
    hm.heights[4:, :] = np.float32(1.0)
    meshes = hm.mesh_tiles(hm.initial_surface_keys())
    n_flat = 0
    n_lip = 0
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        n_flat += int(np.sum(verts[:, 5] > 0.9))
        n_lip += int(np.sum((verts[:, 5] > 0.4) & (verts[:, 5] < 0.6)))
    # Welded corners inside each flat half (36 + 36), not four vertices per cell.
    assert n_flat == 72
    # One sloped strip each side of the wall, at the clamped slope normal.
    assert n_lip == 32


def _mesh_verts(hm: HeightmapBackend) -> np.ndarray:
    chunks = []
    for packed in hm.mesh_tiles(hm.initial_surface_keys()).values():
        if not packed:
            continue
        chunks.append(np.asarray(packed[0], dtype=np.float32).reshape(-1, 12))
    assert chunks
    return np.concatenate(chunks, axis=0)


def _top_normal_at(verts: np.ndarray, x: float, z: float) -> np.ndarray:
    """Shading normal of the top verts at ``(x, z)``.

    Steps keep crisp per-cell tops at exact cell heights, so callers pass the
    owning cell's height (not an averaged corner height).
    """
    pos = verts[:, 0:3]
    nrm = verts[:, 3:6]
    hit = (np.abs(pos[:, 0] - x) < 1e-4) & (np.abs(pos[:, 2] - z) < 1e-3) & (nrm[:, 2] > 0.4)
    assert hit.any()
    got = nrm[hit]
    assert np.allclose(got, got[0], atol=1e-5)
    return got[0]


def test_heightmap_flat_top_normal_is_vertical():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4))
    verts = _mesh_verts(hm)
    top = verts[verts[:, 5] > 0.5]
    assert top.size
    assert np.allclose(top[:, 3:6], (0.0, 0.0, 1.0))


def test_heightmap_ramp_tops_tilt_downhill():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4), tile_size=8)
    slope = np.float32(0.25)
    hm.heights[:, :] = np.float32(1.0) + np.arange(8, dtype=np.float32)[:, None] * slope
    verts = _mesh_verts(hm)
    # Interior column, both X neighbors on the ramp. Height grows toward +X,
    # so the shading normal leans toward -X. Y is constant, so ny stays ~0.
    nrm = _top_normal_at(verts, x=3.0, z=float(hm.heights[2, 0]))
    assert nrm[0] < -0.4
    assert abs(float(nrm[1])) < 0.05
    assert nrm[2] > 0.7
    assert abs(float(np.linalg.norm(nrm)) - 1.0) < 1e-4


def test_heightmap_steep_ramp_normal_stays_upward():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4), tile_size=8)
    hm.heights[:, :] = np.float32(0.5) + np.arange(8, dtype=np.float32)[:, None] * np.float32(2.0)
    verts = _mesh_verts(hm)
    nrm = _top_normal_at(verts, x=3.0, z=float(hm.heights[2, 0]))
    assert nrm[0] < 0.0
    assert abs(float(nrm[2]) - 0.5) < 0.02
    assert abs(float(np.linalg.norm(nrm)) - 1.0) < 1e-4


def test_heightmap_wall_does_not_tilt_adjacent_tread():
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4), tile_size=8)
    slope = np.float32(0.25)
    hm.heights[:, :] = np.float32(5.0) + np.arange(8, dtype=np.float32)[:, None] * slope
    hm.heights[5, :] = np.float32(0.2)
    verts = _mesh_verts(hm)
    interior = _top_normal_at(verts, x=2.0, z=float(hm.heights[2, 0]))
    lip = _top_normal_at(verts, x=4.0, z=float(hm.heights[4, 0]))
    assert lip[2] > 0.7
    assert abs(float(lip[0] - interior[0])) < 0.05
    floor = _top_normal_at(verts, x=5.0, z=0.2)
    assert abs(float(floor[0])) < 0.05
    assert abs(float(floor[2]) - 1.0) < 0.05


def test_heightmap_small_dip_in_flat_tile_is_shaded():
    """A chamfer in a mostly flat tile must not inherit the plateau's +Z normal."""
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(8, 8, 4), tile_size=8)
    hm.heights[:, :] = np.float32(4.0)
    hm.heights[3:6, 3:6] = np.array(
        [
            [3.4, 3.2, 3.4],
            [3.2, 3.0, 3.2],
            [3.4, 3.2, 3.4],
        ],
        dtype=np.float32,
    )
    verts = _mesh_verts(hm)
    flat = _top_normal_at(verts, x=0.0, z=4.0)
    rim = verts[(np.abs(verts[:, 0] - 3.0) < 1e-3) & (verts[:, 5] > 0.5) & (verts[:, 3] > 0.2)]
    assert abs(float(flat[0])) < 0.05
    assert abs(float(flat[2]) - 1.0) < 0.05
    assert rim.shape[0] > 0
    assert float(rim[0, 5]) > 0.5


def _mismatch_heights() -> HeightmapBackend:
    """Bumpy field around one corner that used to crack the welded mesher."""
    bounds = StockBounds(0, 0, 0, 8, 8, 8)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(8, 8, 8), tile_size=16)
    hm.heights[:, :] = np.float32(4.0)
    hm.heights[8, 7] = np.float32(2.5)
    hm.heights[7, 8] = np.float32(6.0)
    hm.heights[8, 8] = np.float32(2.5)
    return hm


def test_heightmap_step_tops_use_exact_cell_heights():
    """Tops must sit at exact cell heights, never averaged corner heights.

    The welded mesher used to average neighbor heights per corner, so adjacent
    cells disagreed on shared edges and left open slits on walls.
    """
    verts = _mesh_verts(_mismatch_heights())
    tops = verts[verts[:, 5] > 0.5]
    assert tops.size
    legit = np.unique(np.asarray(_mismatch_heights().heights).reshape(-1))
    dist = np.abs(tops[:, 2, None] - legit[None, :]).min(axis=1)
    assert np.all(dist < 1e-6)


def test_heightmap_shallow_step_gets_vertical_skirt():
    """Every height step gets a crisp vertical wall, however shallow.

    Steps below the old cliff threshold used to be smoothed into light-shaded
    ramps instead of dark walls.
    """
    bounds = StockBounds(0, 0, 0, 8, 8, 4)
    hm = HeightmapBackend(bounds, 0.5, RectangularStock(8, 8, 4), tile_size=16)
    hm.heights[:, :] = np.float32(4.0)
    hm.heights[8:, :] = np.float32(3.5)
    verts = _mesh_verts(hm)
    wall = verts[(np.abs(verts[:, 0] - 4.0) < 1e-4) & (np.abs(verts[:, 3]) > 0.9)]
    assert wall.shape[0] > 0
    assert np.all(wall[:, 2] <= 4.0 + 1e-6)
    assert np.all(wall[:, 2] >= 3.5 - 1e-6)


def _open_mesh_edges(packed_meshes: dict) -> list:
    """Triangle edges whose midpoint lies on no other face (mesh holes).

    Edges are split at T-junction vertices first, so merged quads meeting
    finer neighbors do not report false gaps.
    """
    tris = []
    for packed in packed_meshes.values():
        if not packed:
            continue
        v = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        idx = np.asarray(packed[1], dtype=np.uint16).reshape(-1, 3)
        pos = v[:, 0:3].astype(np.float64)
        for tri in idx:
            tris.append((pos[tri[0]], pos[tri[1]], pos[tri[2]]))
    assert tris
    uniq: dict = {}
    for a, b, c in tris:
        for p in (a, b, c):
            uniq[(round(float(p[0]), 4), round(float(p[1]), 4), round(float(p[2]), 4))] = p
    pts = np.array(list(uniq.values()))
    seg_count: dict = {}
    seg_mid: dict = {}
    seg_owners: dict = {}
    for k, (a, b, c) in enumerate(tris):
        for u, v in ((a, b), (b, c), (c, a)):
            ab = v - u
            denom = float(ab @ ab)
            if denom < 1e-18:
                continue
            t = ((pts - u) @ ab) / denom
            close = (t > 1e-6) & (t < 1 - 1e-6) & (np.linalg.norm(u + t[:, None] * ab - pts, axis=1) < 1e-3)
            ts = sorted({0.0, 1.0} | {round(float(x), 4) for x in t[close]})
            for m in range(len(ts) - 1):
                p0 = u + ts[m] * ab
                p1 = u + ts[m + 1] * ab
                if float((p1 - p0) @ (p1 - p0)) < 1e-18:
                    continue
                e0 = (round(float(p0[0]), 3), round(float(p0[1]), 3), round(float(p0[2]), 3))
                e1 = (round(float(p1[0]), 3), round(float(p1[1]), 3), round(float(p1[2]), 3))
                key = (e0, e1) if e0 <= e1 else (e1, e0)
                seg_count[key] = seg_count.get(key, 0) + 1
                seg_mid[key] = (p0 + p1) / 2.0
                seg_owners.setdefault(key, []).append(k)
    A = np.array([t[0] for t in tris])
    B = np.array([t[1] for t in tris])
    C = np.array([t[2] for t in tris])
    holes = []
    for key, count in seg_count.items():
        if count != 1:
            continue
        mid = seg_mid[key]
        owners = seg_owners[key]
        covered = False
        for k in range(len(tris)):
            if k in owners:
                continue
            n = np.cross(B[k] - A[k], C[k] - A[k])
            nl = float(np.linalg.norm(n))
            if nl < 1e-18 or abs(float((mid - A[k]) @ n)) / nl > 1e-3:
                continue
            v0, v1 = C[k] - A[k], B[k] - A[k]
            d00, d01, d11 = float(v0 @ v0), float(v0 @ v1), float(v1 @ v1)
            den = d00 * d11 - d01 * d01
            if abs(den) < 1e-18:
                continue
            v2 = mid - A[k]
            vv = (d11 * float(v2 @ v0) - d01 * float(v2 @ v1)) / den
            w = (d00 * float(v2 @ v1) - d01 * float(v2 @ v0)) / den
            if vv > -1e-3 and w > -1e-3 and vv + w < 1 + 1e-3:
                covered = True
                break
        if not covered:
            holes.append(key)
    return holes


def test_heightmap_bumpy_field_has_no_holes():
    """The welded corner averaging left open slits on walls; every boundary
    edge midpoint must lie on another face (or be a T-junction)."""
    hm = _mismatch_heights()
    assert _open_mesh_edges(hm.mesh_tiles(hm.initial_surface_keys())) == []


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
    # Welded corners share vertices. The old unshared tops were four verts per cell.
    assert n_top < 4 * hm.nx * hm.ny


def test_tile_keys_from_window_mask_matches_unique():
    rng = np.random.default_rng(0)
    mask = rng.random((37, 29)) > 0.7
    mask[0, 0] = True
    got = tile_keys_from_window_mask(mask, 5, 9, 16)
    ii, jj = np.nonzero(mask)
    expect = {(int((i + 5) // 16), int((j + 9) // 16), 0) for i, j in zip(ii, jj)}
    assert got == expect
    assert tile_keys_from_window_mask(np.zeros((8, 8), dtype=bool), 0, 0, 16) == set()


def test_pack_quad_meshes_splits_under_kivy_uint16_limit():
    """Kivy Mesh indices are unsigned short; coalesced fields must chunk."""
    import numpy as np

    from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
        MAX_KIVY_MESH_INDICES,
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
        assert len(idx) <= MAX_KIVY_MESH_INDICES
        assert max(idx) <= 65535


def _assert_gles_mesh(verts, indices) -> None:
    nvert = len(verts) // 12
    assert len(indices) <= 65535
    assert 0 < nvert <= 65500
    assert int(max(indices)) < nvert


def test_coalesce_splits_before_gles_index_list_cap():
    """Shared vertices can pass the uint16 vertex cap and still overflow len(indices)."""
    import array

    from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
        VERTEX_FORMAT,
        coalesce_indexed_meshes,
    )

    n_verts = 1000
    n_tris = 4000
    verts = array.array("f", [0.0] * (n_verts * 12))
    indices = array.array("H")
    for t in range(n_tris):
        a = (t * 3) % n_verts
        indices.extend((a, (a + 1) % n_verts, (a + 2) % n_verts))
    parts = [(verts, indices, VERTEX_FORMAT) for _ in range(6)]
    merged = coalesce_indexed_meshes(parts)
    assert len(merged) >= 2
    assert sum(len(idx) for _v, idx, _f in merged) == 6 * n_tris * 3
    for part_verts, part_idx, _fmt in merged:
        _assert_gles_mesh(part_verts, part_idx)


def test_coalesce_splits_oversized_indexed_mesh():
    """An oversized draw is split into GLES-safe parts that keep every triangle intact."""
    import array

    from carveracontroller.addons.stock.simulator.carvers.array_mesh import (
        VERTEX_FORMAT,
        coalesce_indexed_meshes,
    )

    n_verts = 60000
    n_tris = 40000  # 120000 indices: under the vertex cap, over the index cap
    verts = array.array("f", [0.0] * (n_verts * 12))
    # Unique x per vertex so triangles can be matched back after remapping.
    for v in range(n_verts):
        verts[v * 12] = float(v)
    rng = np.random.default_rng(0)
    tri = rng.integers(0, n_verts, size=(n_tris, 3), dtype=np.uint16)
    indices = array.array("H", tri.ravel().tolist())

    parts = coalesce_indexed_meshes([(verts, indices, VERTEX_FORMAT)])
    assert len(parts) >= 2
    got = []
    for part_verts, part_idx, _fmt in parts:
        _assert_gles_mesh(part_verts, part_idx)
        assert len(part_idx) % 3 == 0
        xs = np.frombuffer(memoryview(part_verts), dtype=np.float32).reshape(-1, 12)[:, 0]
        got.append(xs[np.frombuffer(memoryview(part_idx), dtype=np.uint16)].reshape(-1, 3))
    np.testing.assert_array_equal(np.concatenate(got), tri.astype(np.float32))


def test_heightmap_relief_meshes_fit_gles_index_limit():
    """A sloped 64² bin stays under the vertex cap and used to exceed 65535 indices."""
    bounds = StockBounds(0, 0, 0, 64, 64, 10)
    hm = HeightmapBackend(bounds, 1.0, RectangularStock(64, 64, 10))
    xs = np.arange(hm.nx, dtype=np.float32)[:, None]
    ys = np.arange(hm.ny, dtype=np.float32)[None, :]
    hm.heights[:, :] = np.float32(3.0) + np.float32(0.2) * xs + np.float32(0.2) * ys
    meshes = hm.mesh_tiles(hm.initial_surface_keys(), uniform=False)
    parts = [packed for packed in meshes.values() if packed]
    assert len(parts) >= 2
    total = 0
    for verts, indices, _fmt in parts:
        _assert_gles_mesh(verts, indices)
        total += len(indices)
    assert total > 65535


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


def test_heightmap_short_flute_engraver_carves_tapered_walls():
    """Flute shorter than the cone height must not turn the V-bit into a vertical-walled cylinder."""
    tool = ToolDefinition(
        number=2,
        tool_type=ToolType.ENGRAVING,
        diameter=3.175,
        tip_diameter=0.3,
        taper_angle_deg=15.0,
        flute_length=5.0,
        length=40.0,
    )
    bounds = StockBounds(0, -5, 0, 20, 5, 10)
    hm = HeightmapBackend(bounds, 0.05, RectangularStock(20, 10, 10))
    hm.carve_segment((5.0, 0.0, 6.0), (15.0, 0.0, 6.0), tool)

    # Floor sits at the tip depth, the wall must rise with the cone slope (tan 15 deg).
    assert hm.height_at_world(10.0, 0.0) == pytest.approx(6.0, abs=1e-3)
    slope = np.tan(np.radians(15.0))
    for dy in (0.5, 0.8, 1.0):
        expected = 6.0 + (dy - 0.15) / slope
        assert hm.height_at_world(10.0, dy) == pytest.approx(expected, abs=0.1)


def test_heightmap_reports_slot_volume():
    """A flat slot's removed volume matches the stadium, and a recut adds nothing."""
    import math

    from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile

    bounds = StockBounds(0, -10, 0, 40, 10, 10)
    cell = 0.25
    shape = RectangularStock(40, 20, 10)
    tool = _flat_tool(6.0)
    profile = resolve_cutting_profile(tool, tool_unit_scale=1.0)
    segment = ((10.0, 0.0, 8.0), (30.0, 0.0, 8.0), 0.0, 0.0)

    plain = HeightmapBackend(bounds, cell, shape)
    measured = HeightmapBackend(bounds, cell, shape)
    volumes = np.zeros(2, dtype=np.float64)
    plain.carve_segments([segment], profile)
    measured.carve_segments([segment, segment], profile, volumes=volumes)
    assert np.array_equal(plain.heights, measured.heights)

    length = 20.0
    diameter = 6.0
    depth = 2.0
    analytic = (length * diameter + math.pi * (diameter / 2.0) ** 2) * depth
    perimeter = 2.0 * length + math.pi * diameter
    assert abs(float(volumes[0]) - analytic) < cell * depth * perimeter
    assert float(volumes[1]) == 0.0
