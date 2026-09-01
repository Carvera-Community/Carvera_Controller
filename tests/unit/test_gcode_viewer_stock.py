"""Stock playback presentation helpers (no full Kivy widget tree)."""

from unittest.mock import MagicMock

import pytest

from carveracontroller.GcodeViewer import GCodeViewer


def _viewer(**kwargs) -> GCodeViewer:
    viewer = GCodeViewer.__new__(GCodeViewer)
    viewer.simulate_cut = True
    viewer.dynamic_display = False
    viewer.stock_mesh_while_playing = False
    viewer._defer_carved_stock = False
    viewer.raw_positions = [0.0, 0.0, 0.0]
    viewer.cur_line_index = 0
    viewer._stock_simulator = MagicMock()
    for key, value in kwargs.items():
        setattr(viewer, key, value)
    return viewer


def test_carved_stock_hidden_while_deferred_after_pause():
    viewer = _viewer(dynamic_display=False, _defer_carved_stock=True)
    assert viewer._carved_stock_visible() is False


def test_carved_stock_visible_when_paused_after_flush():
    viewer = _viewer(dynamic_display=False, _defer_carved_stock=False)
    assert viewer._carved_stock_visible() is True


def test_carved_stock_hidden_while_playing_without_live_mesh():
    viewer = _viewer(dynamic_display=True, stock_mesh_while_playing=False)
    assert viewer._carved_stock_visible() is False


def test_pause_defers_carved_stock_when_live_mesh_off():
    viewer = _viewer()
    viewer._sync_play_mesh_policy = MagicMock()

    viewer._on_dynamic_display_changed(None, False)

    assert viewer._defer_carved_stock is True
    viewer._sync_play_mesh_policy.assert_called_once()
    viewer._stock_simulator.request_mesh_flush.assert_called_once()


def test_pause_does_not_defer_when_live_mesh_on():
    viewer = _viewer(stock_mesh_while_playing=True)
    viewer._sync_play_mesh_policy = MagicMock()

    viewer._on_dynamic_display_changed(None, False)

    assert viewer._defer_carved_stock is False
    viewer._stock_simulator.request_mesh_flush.assert_called_once()


def test_play_clears_deferred_carved_stock():
    viewer = _viewer(_defer_carved_stock=True)
    viewer._sync_play_mesh_policy = MagicMock()

    viewer._on_dynamic_display_changed(None, True)

    assert viewer._defer_carved_stock is False
    viewer._stock_simulator.request_mesh_flush.assert_not_called()


def test_mesh_apply_reveals_carved_stock_after_deferred_pause():
    viewer = _viewer(_defer_carved_stock=True)
    viewer._carved_meshes = {}
    viewer.carvedmesh = MagicMock()
    viewer.carvedmesh.children = []
    viewer._carved_mesh_anchor = object()
    viewer._update_carved_uniforms = MagicMock()
    viewer._rebuild_stock_mesh = MagicMock()
    viewer._ensure_stock_on_canvas = MagicMock()

    viewer._apply_stock_meshes({})

    assert viewer._defer_carved_stock is False
    viewer._rebuild_stock_mesh.assert_called_once()
    viewer._ensure_stock_on_canvas.assert_called_once()


def test_clear_all_does_not_reveal_deferred_carved_stock():
    viewer = _viewer(_defer_carved_stock=True)
    viewer._clear_carved_meshes = MagicMock()
    viewer._rebuild_stock_mesh = MagicMock()
    viewer._ensure_stock_on_canvas = MagicMock()

    viewer._apply_stock_meshes({"__clear_all__": None})

    assert viewer._defer_carved_stock is False
    viewer._clear_carved_meshes.assert_called_once()
    viewer._rebuild_stock_mesh.assert_not_called()
    viewer._ensure_stock_on_canvas.assert_not_called()


def test_stock_uniforms_keep_a_axis_rotation():
    """Orbit/resize must not reset stock A rotation to identity."""
    from kivy.graphics.transformation import Matrix

    rot = Matrix().rotate(0.8, 1, 0, 0)
    viewer = _viewer(
        _stock_rotation_mat=rot,
        lines_center=[0.0, 0.0, 0.0],
        m_viewMatrix=Matrix(),
        _proj_matrix=Matrix(),
        stock_bounds_mm=None,
    )
    viewer.stockmesh = {}
    viewer.carvedmesh = {}
    viewer._stock_scale = lambda: 1.0

    GCodeViewer._update_stock_uniforms(viewer)
    GCodeViewer._update_carved_uniforms(viewer)

    assert viewer.stockmesh["rotation_mat"] is rot
    assert viewer.carvedmesh["rotation_mat"] is rot


def test_carved_uniforms_include_material_brdf():
    from kivy.graphics.transformation import Matrix

    from carveracontroller.addons.stock.stock_material import MATERIAL_PCB, style_for_material

    viewer = _viewer(
        _stock_rotation_mat=Matrix(),
        lines_center=[0.0, 0.0, 0.0],
        m_viewMatrix=Matrix(),
        _proj_matrix=Matrix(),
        stock_bounds_mm=None,
        stock_material=MATERIAL_PCB,
        stock_shape=None,
    )
    viewer.carvedmesh = {}
    viewer._stock_scale = lambda: 1.0

    GCodeViewer._update_carved_uniforms(viewer)

    style = style_for_material(MATERIAL_PCB)
    assert viewer.carvedmesh["metallic"] == style.metallic
    assert viewer.carvedmesh["interior_metallic"] == style.resolved_interior_metallic()
    assert viewer.carvedmesh["roughness"] == style.roughness
    assert viewer.carvedmesh["interior_roughness"] == style.resolved_interior_roughness()
    assert viewer.carvedmesh["interior_color"] == list(style.resolved_interior_rgb())
    assert viewer.carvedmesh["use_two_tone"] == 1.0


def _uniforms_viewer(**kwargs):
    from kivy.graphics.transformation import Matrix

    viewer = _viewer(
        _stock_rotation_mat=Matrix(),
        lines_center=[0.0, 0.0, 0.0],
        m_viewMatrix=Matrix(),
        _proj_matrix=Matrix(),
        **kwargs,
    )
    viewer.carvedmesh = {}
    viewer._stock_scale = lambda: 1.0
    return viewer


def test_standing_cylinder_pcb_keeps_foil_not_od_skin():
    """Copper stays on +Z; 3-axis cylinders do not use the rotary OD path."""
    from carveracontroller.addons.stock.stock_geometry import StockBounds
    from carveracontroller.addons.stock.stock_shape import CylindricalStock

    bounds = StockBounds(0.0, 0.0, 0.0, 20.0, 20.0, 5.0)
    viewer = _uniforms_viewer(
        stock_bounds_mm=bounds,
        stock_shape=CylindricalStock(diameter_mm=20.0, height_mm=5.0),
        stock_material="pcb",
    )

    GCodeViewer._update_carved_uniforms(viewer)

    assert viewer.carvedmesh["cylindrical_skin"] == 0.0
    assert viewer.carvedmesh["use_two_tone"] == 1.0


def test_rotary_cylinder_keeps_x_axis_skin_and_yz_radius():
    from carveracontroller.addons.stock.stock_geometry import StockBounds
    from carveracontroller.addons.stock.stock_shape import RotaryCylindricalStock

    bounds = StockBounds(0.0, -15.0, -15.0, 80.0, 15.0, 15.0)
    viewer = _uniforms_viewer(
        stock_bounds_mm=bounds,
        stock_shape=RotaryCylindricalStock(diameter_mm=30.0, length_mm=80.0),
        stock_material="aluminum",
    )

    GCodeViewer._update_carved_uniforms(viewer)

    assert viewer.carvedmesh["cylindrical_skin"] == 1.0
    assert viewer.carvedmesh["use_two_tone"] == 0.0
    assert viewer.carvedmesh["stock_radius"] == pytest.approx(15.0)


def test_pcb_surface_eps_thinner_than_isolation_and_cell():
    """Z=-0.05 isolation must fall through copper; do not use voxel cell size."""
    viewer = _viewer(stock_material="pcb")
    viewer._stock_scale = lambda: 1.0
    viewer._stock_simulator.hud_stats.return_value = {"cell_size_mm": 0.5}

    eps = GCodeViewer._surface_z_eps_viewer(viewer)
    assert eps == pytest.approx(0.035)
    assert eps < 0.05


def test_two_tone_skin_uses_stock_local_space_not_rotated_z():
    """Foil/skin must follow the stock face under A rotation; rotary caps stay core."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "carveracontroller" / "shaders" / "carved_stock.glsl").read_text()
    assert "step(stock_z_max - surface_z_eps, stock_pos.z)" in src
    assert "step(stock_z_max - surface_z_eps, world_z)" not in src
    assert "is_surface = (1.0 - cap) * outward * at_od;" in src
    assert "cap * at_cap" not in src


def test_raw_feed_z_max_uses_unrotated_wcs_z():
    """A-baked display Z is near 0 at A=90; stock estimate must use machine Z."""
    raw_zs = [10.0] * 2 + [22.0] * 18
    raw: list[float] = []
    baked: list[float] = []
    feeds: list[float] = []
    for i, z in enumerate(raw_zs):
        raw.extend((float(i), 0.0, z))
        baked.extend((float(i), -z, 0.0))
        feeds.append(1000.0)
    viewer = _viewer(
        raw_positions=raw,
        positions=baked,
        raw_feed_rates=feeds,
        z_max_mm=0.0,
    )
    assert GCodeViewer.raw_feed_z_max_mm(viewer) == pytest.approx(22.0)


def test_format_sim_hud_cylindrical_names_od():
    viewer = _viewer()
    viewer._stock_simulator.hud_stats.return_value = {
        "carver": "cylindrical",
        "cell_size_mm": 0.38,
        "grid_nx": 800,
        "grid_ny": 472,
        "grid_nz": 1,
        "stock_diameter_mm": 50.0,
        "checkpoint_count": 0,
        "checkpoint_max_count": 0,
        "checkpoint_head_vertex": 0,
    }
    text = viewer._format_sim_hud_text()
    assert "Cylindrical: 800x472" in text
    assert "0.38 mm along X and at Ø50" in text
    assert "mm/cell" not in text


def test_format_sim_hud_heightmap_keeps_mm_per_cell():
    viewer = _viewer()
    viewer._stock_simulator.hud_stats.return_value = {
        "carver": "heightmap",
        "cell_size_mm": 0.21,
        "grid_nx": 200,
        "grid_ny": 200,
        "grid_nz": 1,
        "checkpoint_count": 0,
        "checkpoint_max_count": 0,
        "checkpoint_head_vertex": 0,
    }
    text = viewer._format_sim_hud_text()
    assert "Heightmap: 200x200 - 0.21mm/cell" in text


def test_simulation_available_with_cam_tool_table():
    viewer = _viewer(tool_table={1: object()}, raw_tools=[])
    assert viewer.simulation_available() is True


def test_simulation_available_laser_only_without_tool_table():
    from carveracontroller.CNC import LASER_TOOL_NUMBER, ZPROBE_TOOL_NUMBER

    viewer = _viewer(tool_table={}, raw_tools=[ZPROBE_TOOL_NUMBER, LASER_TOOL_NUMBER, LASER_TOOL_NUMBER])
    assert viewer.simulation_available() is True


def test_simulation_available_laser_and_3d_probe_without_tool_table():
    from carveracontroller.CNC import LASER_TOOL_NUMBER, PROBE_3D_TOOL_NUMBER

    viewer = _viewer(tool_table={}, raw_tools=[PROBE_3D_TOOL_NUMBER, LASER_TOOL_NUMBER])
    assert viewer.simulation_available() is True


def test_simulation_unavailable_mill_without_tool_table():
    from carveracontroller.CNC import LASER_TOOL_NUMBER

    viewer = _viewer(tool_table={}, raw_tools=[LASER_TOOL_NUMBER, 1])
    assert viewer.simulation_available() is False


def test_simulation_unavailable_probe_only_without_tool_table():
    from carveracontroller.CNC import PROBE_3D_TOOL_NUMBER, ZPROBE_TOOL_NUMBER

    viewer = _viewer(tool_table={}, raw_tools=[ZPROBE_TOOL_NUMBER, PROBE_3D_TOOL_NUMBER])
    assert viewer.simulation_available() is False


def test_simulation_unavailable_empty_path_without_tool_table():
    viewer = _viewer(tool_table={}, raw_tools=[])
    assert viewer.simulation_available() is False


def test_set_stock_material_only_skips_simulation_restart():
    from carveracontroller.addons.stock.stock_geometry import StockBounds
    from carveracontroller.addons.stock.stock_material import DEFAULT_MATERIAL, MATERIAL_PCB
    from carveracontroller.addons.stock.stock_shape import RectangularStock

    bounds = StockBounds(0, 0, 0, 10, 10, 5)
    shape = RectangularStock(width_mm=10, length_mm=10, height_mm=5)
    viewer = _viewer(
        stock_bounds_mm=bounds,
        stock_shape=shape,
        stock_visible=True,
        simulate_cut=True,
        stock_mesh_while_playing=False,
        stock_voxel_resolution="low",
        stock_checkpoint_level="medium",
        stock_carver_mode="auto",
        stock_material=DEFAULT_MATERIAL,
    )
    viewer.simulation_available = lambda: True
    viewer._rebuild_stock_mesh = MagicMock()
    viewer._ensure_stock_on_canvas = MagicMock()
    viewer._restart_stock_simulation = MagicMock()
    viewer._update_carved_uniforms = MagicMock()
    viewer._sim_hud_trigger = MagicMock()

    GCodeViewer.set_stock(
        viewer,
        bounds,
        visible=True,
        simulate_cut=True,
        voxel_resolution="low",
        checkpoint_level="medium",
        mesh_while_playing=False,
        carver_mode="auto",
        shape=shape,
        material=MATERIAL_PCB,
    )

    viewer._rebuild_stock_mesh.assert_called_once()
    viewer._update_carved_uniforms.assert_called_once()
    viewer._restart_stock_simulation.assert_not_called()
    assert viewer.stock_material == MATERIAL_PCB


def test_set_stock_resolution_change_restarts_simulation():
    from carveracontroller.addons.stock.stock_geometry import StockBounds
    from carveracontroller.addons.stock.stock_shape import RectangularStock

    bounds = StockBounds(0, 0, 0, 10, 10, 5)
    shape = RectangularStock(width_mm=10, length_mm=10, height_mm=5)
    viewer = _viewer(
        stock_bounds_mm=bounds,
        stock_shape=shape,
        stock_visible=True,
        simulate_cut=True,
        stock_mesh_while_playing=False,
        stock_voxel_resolution="low",
        stock_checkpoint_level="medium",
        stock_carver_mode="auto",
        stock_material="beige",
    )
    viewer.simulation_available = lambda: True
    viewer._rebuild_stock_mesh = MagicMock()
    viewer._ensure_stock_on_canvas = MagicMock()
    viewer._restart_stock_simulation = MagicMock()
    viewer._update_carved_uniforms = MagicMock()
    viewer._sim_hud_trigger = MagicMock()

    GCodeViewer.set_stock(
        viewer,
        bounds,
        visible=True,
        simulate_cut=True,
        voxel_resolution="high",
        checkpoint_level="medium",
        mesh_while_playing=False,
        carver_mode="auto",
        shape=shape,
        material="beige",
    )

    viewer._restart_stock_simulation.assert_called_once()
