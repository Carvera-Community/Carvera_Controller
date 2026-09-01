"""Unit tests for the cylindrical r(x, θ) stock carver."""

from __future__ import annotations

import numpy as np

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.cylindrical import CylindricalBackend
from carveracontroller.addons.stock.simulator.carvers.cylindrical.backend import (
    MAX_CYLINDRICAL_N_THETA,
    _revolution_cut_radius,
    _xyz_inside_tool,
    pick_cylindrical_dims,
    pose_ts_cell_aligned,
    shell_floor_radius_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds, rotate_yz
from carveracontroller.addons.stock.stock_shape import RotaryCylindricalStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType


def _flat_tool(diameter: float = 6.0, flute_length: float = 8.0) -> ToolDefinition:
    return ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=diameter,
        flute_length=flute_length,
        length=40.0,
    )


def _vbit(
    diameter: float = 6.0,
    tip_diameter: float = 0.2,
    taper_angle_deg: float = 15.0,
    flute_length: float = 20.0,
) -> ToolDefinition:
    return ToolDefinition(
        number=2,
        tool_type=ToolType.CHAMFER_MILL,
        diameter=diameter,
        tip_diameter=tip_diameter,
        taper_angle_deg=taper_angle_deg,
        flute_length=flute_length,
        length=40.0,
    )


def test_cylindrical_seeds_full_radius():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 1.0, shape)
    assert cyl.hud_stats()["carver"] == "cylindrical"
    assert abs(cyl.hud_stats()["stock_diameter_mm"] - 28.0) < 1e-6
    r = cyl.radius_at(20.0, 0.0)
    assert r is not None and abs(r - 14.0) < 1e-3


def test_indexed_a90_clears_side_not_top():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=90.0, a1=90.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(20.0, y, z)
    assert cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_pose_ts_point_is_single_sample():
    ts = pose_ts_cell_aligned((0, 0, 8), (0, 0, 8), 0.0, 0.0, min_x=0.0, cell_size_mm=0.5, d_theta_deg=2.0)
    assert list(ts) == [0.0]


def test_pose_ts_constant_a_hits_x_centers():
    ts = pose_ts_cell_aligned(
        (0.0, 0.0, 8.0),
        (10.0, 0.0, 8.0),
        0.0,
        0.0,
        min_x=0.0,
        cell_size_mm=0.5,
        d_theta_deg=2.0,
    )
    assert ts[0] == 0.0 and ts[-1] == 1.0
    xs = ts * 10.0
    for wx in np.arange(0.25, 10.0, 0.5):
        assert np.min(np.abs(xs - wx)) < 1e-8


def test_pose_ts_cell_aligned_hits_x_and_theta_centers():
    ts = pose_ts_cell_aligned(
        (8.0, 0.0, 8.0),
        (16.0, 0.0, 8.0),
        0.0,
        90.0,
        min_x=0.0,
        cell_size_mm=0.5,
        d_theta_deg=2.0,
    )
    assert ts[0] == 0.0 and ts[-1] == 1.0
    xs = 8.0 + ts * 8.0
    # Every X cell center between 8 and 16 is a stamp (8.25, 8.75, ..., 15.75).
    for wx in np.arange(8.25, 16.0, 0.5):
        assert np.min(np.abs(xs - wx)) < 1e-8
    # Every θ cell center in (0, 90) too (1°, 3°, ..., 89°).
    a = ts * 90.0
    for ac in np.arange(1.0, 90.0, 2.0):
        assert np.min(np.abs(a - ac)) < 1e-8


def test_indexed_a90_feed_clears_along_x():
    """Constant-A X feeds must sweep the whole segment, not only p0."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((8.0, 0.0, 8.0), (32.0, 0.0, 8.0), tool, a0=90.0, a1=90.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(8.0, y, z)
    assert not cyl.is_solid_at_world(20.0, y, z)
    assert not cyl.is_solid_at_world(32.0, y, z)
    assert cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_wrapping_shallow_helix_clears_mid_x():
    """Small ΔA over a long X move must still sample along XYZ."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((6.0, 0.0, 8.0), (34.0, 0.0, 8.0), tool, a0=0.0, a1=4.0)
    assert not cyl.is_solid_at_world(6.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(34.0, 0.0, 10.0)


def test_wrapping_a_clears_arc():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    dirty = cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=90.0)
    assert dirty
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(20.0, y, z)


def test_wrapping_full_revolution_clears_every_theta():
    """A 360° wrap at constant XYZ must cut the whole ring, not only the start A."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    dirty = cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=360.0)
    assert dirty
    for a in (0.0, 90.0, 180.0, 270.0):
        y, z = rotate_yz(0.0, 10.0, a)
        assert not cyl.is_solid_at_world(20.0, y, z)


def test_wrapping_helix_clears_along_x():
    """ΔA-dominated helix should sample poses, not only the endpoints."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((8.0, 0.0, 8.0), (16.0, 0.0, 8.0), tool, a0=0.0, a1=90.0)
    assert not cyl.is_solid_at_world(8.0, 0.0, 10.0)
    y90, z90 = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(16.0, y90, z90)
    y45, z45 = rotate_yz(0.0, 10.0, 45.0)
    assert not cyl.is_solid_at_world(12.0, y45, z45)
    assert cyl.is_solid_at_world(16.0, 0.0, 10.0)


def test_cylindrical_mesh_tiles():
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    assert list(meshes) == [(0, 0, 0)]
    assert any(v is not None for v in meshes.values())


def test_cylindrical_mesh_is_regular_grid():
    """One quad per (x, θ) cell so sloped features don't open T-junction holes."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=32, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=32.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    n_quads = (cyl.nx - 1) * cyl.n_theta + 2 * cyl.n_theta
    assert n_verts == n_quads * 4


def test_cylindrical_sloped_mesh_stays_regular():
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    xs = np.linspace(0.0, 1.0, cyl.nx, dtype=np.float32)[:, None]
    th = np.linspace(0.0, 1.0, cyl.n_theta, dtype=np.float32)[None, :]
    cyl.radii[:, :] = 6.0 + 3.0 * xs + 2.0 * th
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    n_quads = (cyl.nx - 1) * cyl.n_theta + 2 * cyl.n_theta
    assert n_verts == n_quads * 4


def test_cylindrical_slope_triangles_face_outward():
    """Back-face culling hides any triangle whose geometric normal points inward."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    xs = np.linspace(0.0, 1.0, cyl.nx, dtype=np.float32)[:, None]
    th = np.linspace(0.0, 1.0, cyl.n_theta, dtype=np.float32)[None, :]
    cyl.radii[:, :] = 6.0 + 3.0 * xs + 2.0 * th
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    flipped = 0
    checked = 0
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        idx = np.asarray(packed[1], dtype=np.int32)
        pos = verts[:, :3]
        for i in range(0, idx.size, 3):
            a, b, c = pos[idx[i]], pos[idx[i + 1]], pos[idx[i + 2]]
            n = np.cross(b - a, c - a)
            if np.linalg.norm(n) < 1e-10:
                continue
            # End caps are constant-X; skip them (normal is ±X, not radial).
            if abs(a[0] - b[0]) < 1e-4 and abs(a[0] - c[0]) < 1e-4:
                continue
            mid = (a + b + c) / 3.0
            hint = np.array((0.0, mid[1] - cyl.axis_y, mid[2] - cyl.axis_z), dtype=np.float64)
            checked += 1
            if float(np.dot(n, hint)) <= 0.0:
                flipped += 1
    assert checked > 0
    assert flipped == 0


def _mesh_normals(meshes: dict) -> np.ndarray:
    rows = []
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        rows.append(verts[:, 3:6])
    assert rows
    return np.concatenate(rows, axis=0)


def test_cylindrical_flat_cut_sets_radius_to_tip():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=0.0)
    r = cyl.radius_at(20.0, 0.0)
    assert r is not None
    assert abs(r - 8.0) < 0.6
    assert cyl.is_solid_at_world(20.0, 0.0, 7.5)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_cylindrical_ball_mill_clears_top():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.BALL_END_MILL,
        diameter=6.0,
        flute_length=8.0,
        length=40.0,
    )
    dirty = cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=0.0)
    assert dirty
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert cyl.is_solid_at_world(20.0, 0.0, 7.0)


def test_cylindrical_mesh_has_end_caps():
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    nrm = _mesh_normals(cyl.mesh_tiles(cyl.initial_surface_keys()))
    assert np.any(nrm[:, 0] < -0.5)
    assert np.any(nrm[:, 0] > 0.5)


def test_cylindrical_y_offset_clears_side():
    """Indexed A=0 with Y ≠ 0 must center the θ window on the tool azimuth."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 8.0, 10.0), (20.0, 8.0, 10.0), tool, a0=0.0, a1=0.0)
    assert not cyl.is_solid_at_world(20.0, 8.0, 11.0)
    assert cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_cylindrical_theta_pad_uses_tangent_half_angle():
    """θ pad must be asin(R/D); atan(R/D) misses surface hits on a Y-offset mill."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=40, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=10.0)
    cyl.carve_segment((20.0, 4.0, 1.0), (20.0, 4.0, 1.0), tool, a0=0.0, a1=0.0)
    # Surface point at θ≈17°. Tool azimuth is ~76°; atan(reach/D)+dθ ≈ 43°
    # does not cover it, asin (tangent) ≈ 61° does.
    assert not cyl.is_solid_at_world(20.0, 2.8, 9.1)
    assert cyl.is_solid_at_world(20.0, 0.0, -9.0)


def test_cylindrical_plunge_clears_far_theta():
    """A plunge that overlaps the A-axis must not drop the far θ half."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 0.0, 14.0), (20.0, 0.0, -14.0), tool, a0=0.0, a1=0.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, -10.0)


def _shell_triangle_stats(cyl: CylindricalBackend) -> tuple[int, int, int, int]:
    """Return (checked, flipped, near-axis, degenerate) counts for shell triangles."""
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    flipped = 0
    axis_hits = 0
    degen = 0
    checked = 0
    ay, az = float(cyl.axis_y), float(cyl.axis_z)
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        idx = np.asarray(packed[1], dtype=np.int32)
        pos = verts[:, :3]
        for i in range(0, idx.size, 3):
            a, b, c = pos[idx[i]], pos[idx[i + 1]], pos[idx[i + 2]]
            n = np.cross(b - a, c - a)
            if abs(a[0] - b[0]) < 1e-4 and abs(a[0] - c[0]) < 1e-4:
                continue
            if np.linalg.norm(n) < 1e-10:
                degen += 1
                continue
            mid = (a + b + c) / 3.0
            hint = np.array((0.0, mid[1] - ay, mid[2] - az), dtype=np.float64)
            checked += 1
            if float(np.dot(n, hint)) <= 0.0:
                flipped += 1
            rs = [float(np.hypot(p[1] - ay, p[2] - az)) for p in (a, b, c)]
            if min(rs) < 0.5 * shell_floor_radius_mm(cyl.cell_size):
                axis_hits += 1
    return checked, flipped, axis_hits, degen


def test_cylindrical_through_axis_does_not_pinch_mesh():
    """Past-center wrapping must keep a closed tube, not pinch onto the A-axis.

    Occupancy may go to r=0; the mesh inflates that to a hairline radius so θ
    vertices stay distinct. Dropping those dexels opened a hole in the skin.
    """
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=40, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.4, shape)
    x = 20.0
    z_vals = np.linspace(3.0, -5.0, 9)
    poses = [((x, 0.0, float(z)), 45.0 * i) for i, z in enumerate(z_vals)]
    for i in range(1, len(poses)):
        (p0, a0), (p1, a1) = poses[i - 1], poses[i]
        cyl.carve_segment(p0, p1, _vbit(), a0=a0, a1=a1)
    ix = cyl._x_index(x)
    ring = cyl.radii[ix]
    assert np.any(ring <= 1e-6)
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    n_quads = (cyl.nx - 1) * cyl.n_theta + 2 * cyl.n_theta
    assert n_verts == n_quads * 4
    checked, flipped, axis_hits, degen = _shell_triangle_stats(cyl)
    assert checked > 0
    assert flipped == 0
    assert axis_hits == 0
    assert degen == 0


def test_cylindrical_thin_waist_still_meshes():
    """A uniform leftover radius well above the through-cut floor stays a tube."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    cyl.radii[:, :] = np.float32(0.3)
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    n_quads = (cyl.nx - 1) * cyl.n_theta + 2 * cyl.n_theta
    assert n_verts == n_quads * 4
    checked, flipped, axis_hits, degen = _shell_triangle_stats(cyl)
    assert checked > 0
    assert flipped == 0
    assert axis_hits == 0
    assert degen == 0


def test_pick_cylindrical_dims_caps_n_theta_on_puck():
    """A tiny cell_size on a short Ø80 puck must not explode θ samples."""
    bounds = StockBounds(0, -40, -40, 5, 40, 40)
    nx, n_theta, d_theta = pick_cylindrical_dims(bounds, 0.01, 80.0)
    assert nx == 500
    assert n_theta == MAX_CYLINDRICAL_N_THETA
    assert n_theta % 4 == 0
    assert n_theta * d_theta == 360.0


def test_cylindrical_vbit_point_clears_tip():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), _vbit(), a0=0.0, a1=0.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert cyl.is_solid_at_world(20.0, 0.0, 7.0)


def test_cylindrical_vbit_wrapping_clears_arc():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    dirty = cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), _vbit(), a0=0.0, a1=90.0)
    assert dirty
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(20.0, y, z)


def test_cylindrical_vbit_short_wrap_step_clears():
    """Sub-cell XYZ + small ΔA finishing steps must still use the point-pose cut."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    cyl.carve_segment((20.0, 0.0, 8.0), (20.07, 0.0, 8.0), _vbit(), a0=0.0, a1=1.5)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(20.07, 0.0, 10.0)


def test_cylindrical_wrapping_z_bump_chord_overcuts_vbit():
    """XYZ chord of a wrapping Z bump overcuts; the polyline keeps the ridge.

    Same geometry as 4-axis surface following: X fixed, A advances, Z jumps
    away from the axis then returns. A V-bit chord through the bump gouges.
    """
    bounds = StockBounds(min_x=0, min_y=-16, min_z=-16, max_x=40, max_y=16, max_z=16)
    shape = RotaryCylindricalStock(diameter_mm=32.0, length_mm=40.0)
    tool = _vbit()
    x = 20.0
    poses = (
        ((x, 0.0, 10.0), 0.0),
        ((x, 0.0, 10.2), 3.0),
        ((x, 0.0, 12.0), 6.0),
        ((x, 0.0, 10.2), 9.0),
        ((x, 0.0, 10.0), 12.0),
    )
    cyl_poly = CylindricalBackend(bounds, 0.4, shape)
    for i in range(1, len(poses)):
        (p0, a0), (p1, a1) = poses[i - 1], poses[i]
        cyl_poly.carve_segment(p0, p1, tool, a0=a0, a1=a1)
    cyl_chord = CylindricalBackend(bounds, 0.4, shape)
    cyl_chord.carve_segment(poses[0][0], poses[-1][0], tool, a0=poses[0][1], a1=poses[-1][1])
    # Tool sits on +Z; occupancy θ is atan2(Y,Z)−A ≈ −A.
    r_poly = cyl_poly.radius_at(x, -6.0)
    r_chord = cyl_chord.radius_at(x, -6.0)
    assert r_poly is not None and r_chord is not None
    assert r_poly > r_chord + 0.3


def test_cylindrical_vbit_helix_floor_is_smooth():
    """Helix stamps at cell centers so a V-tip does not leave X-wise bumps."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    cyl.carve_segment((8.0, 0.0, 8.0), (16.0, 0.0, 8.0), _vbit(), a0=0.0, a1=90.0)
    i0 = cyl._x_index(8.0)
    i1 = cyl._x_index(15.5)
    floor = cyl.radii[i0 : i1 + 1].min(axis=1).astype(np.float64)
    # Tip at Z=8; a grid-aligned V-bit should cut every X cell to about that.
    assert float(np.max(floor) - np.min(floor)) < 0.08
    assert float(np.max(floor)) < 8.25


def _binary_cut_point(cyl: CylindricalBackend, tip, angle, zs, rs, max_r, slab, wx, it):
    uy, uz, y0, z0_axis = cyl._ray_frame(it, angle)

    def _inside(r_field):
        valid = r_field >= 0.0
        yy = y0 + r_field * uy[None, :]
        zz = z0_axis + r_field * uz[None, :]
        return valid & _xyz_inside_tool(wx[:, None], yy, zz, tip, tip, zs, rs, None, max_r)

    hit = _inside(slab)
    hit |= _inside(np.maximum(slab - cyl.cell_size * 0.5, 0.0))
    if not hit.any():
        return slab, hit
    lo = np.zeros_like(slab)
    hi = slab.copy()
    for _ in range(cyl._radius_search_iters()):
        mid = 0.5 * (lo + hi)
        ins = _inside(mid)
        hi = np.where(ins, mid, hi)
        lo = np.where(ins, lo, mid)
    return np.maximum(lo, 0.0), hit


def test_revolution_cut_matches_binary_search_for_vbit():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    cyl.radii[:, :] = np.float32(9.0)
    profile = resolve_cutting_profile(_vbit())
    zs = np.array([z for z, _r in profile], dtype=np.float64)
    rs = np.array([r for _z, r in profile], dtype=np.float64)
    max_r = float(np.max(rs))
    tip = (20.0, 0.0, 8.0)
    angle = 40.0
    it = cyl._theta_window_indices(tip, tip, angle, max_r)
    pad = max_r + cyl.cell_size
    ix0 = max(0, cyl._x_index(tip[0] - pad))
    ix1 = min(cyl.nx - 1, cyl._x_index(tip[0] + pad))
    wx = cyl.bounds.min_x + (np.arange(ix0, ix1 + 1, dtype=np.float64) + 0.5) * cyl.cell_size
    slab = cyl.radii[ix0 : ix1 + 1][:, it].astype(np.float64)
    uy, uz, y0, z0_axis = cyl._ray_frame(it, angle)
    new_an, hit_an = _revolution_cut_radius(wx, uy, uz, y0, z0_axis, tip, zs, rs, slab, cyl.cell_size * 0.5)
    new_bin, hit_bin = _binary_cut_point(cyl, tip, angle, zs, rs, max_r, slab, wx, it)
    assert hit_an.sum() == hit_bin.sum() or np.sum(hit_an ^ hit_bin) <= 2
    both = hit_an & hit_bin
    assert both.any()
    # Binary search stops at ~stock/2^iters; analytic should be at least that close.
    assert np.max(np.abs(new_an[both] - new_bin[both])) < 0.02
