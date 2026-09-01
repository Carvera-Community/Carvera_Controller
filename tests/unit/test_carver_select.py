"""Unit tests for carver backend auto-selection and overrides."""

from __future__ import annotations

from carveracontroller.addons.stock.simulator.carver_select import (
    BACKEND_CYLINDRICAL,
    BACKEND_HEIGHTMAP,
    BACKEND_VOXEL,
    MODE_AUTO,
    MODE_CYLINDRICAL,
    MODE_HEIGHTMAP,
    MODE_VOXEL,
    normalize_carver_mode,
    profile_undercuts,
    recommend_carver,
    resolve_cutting_profile,
)
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType


def _flat_tool(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=6.0,
        flute_length=10.0,
        length=40.0,
    )


def _vbit(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.CHAMFER_MILL,
        diameter=6.0,
        tip_diameter=0.2,
        taper_angle_deg=15.0,
        flute_length=10.0,
        length=40.0,
    )


def _thread_mill(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.THREAD_MILL,
        diameter=6.0,
        thread_depth=0.5,
        thread_pitch=1.0,
        flute_length=10.0,
        length=40.0,
    )


def _lollipop(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.LOLLIPOP_MILL,
        diameter=6.0,
        flute_length=10.0,
        length=40.0,
    )


def _ball(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.BALL_END_MILL,
        diameter=6.0,
        flute_length=10.0,
        length=40.0,
    )


def _bull_nose(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.BULL_NOSE_END_MILL,
        diameter=6.0,
        corner_radius=1.0,
        flute_length=10.0,
        length=40.0,
    )


def _radius_mill(number: int = 1) -> ToolDefinition:
    return ToolDefinition(
        number=number,
        tool_type=ToolType.RADIUS_MILL,
        diameter=4.0,
        corner_radius=1.0,
        flute_length=10.0,
        length=40.0,
    )


def test_normalize_carver_mode():
    assert normalize_carver_mode("AUTO") == MODE_AUTO
    assert normalize_carver_mode("bogus") == MODE_AUTO
    assert normalize_carver_mode(MODE_VOXEL) == MODE_VOXEL


def test_profile_undercuts_only_reentrant_silhouettes():
    thread = resolve_cutting_profile(_thread_mill())
    lolli = resolve_cutting_profile(_lollipop())
    flat = resolve_cutting_profile(_flat_tool())
    vbit = resolve_cutting_profile(_vbit())
    ball = resolve_cutting_profile(_ball())
    bull = resolve_cutting_profile(_bull_nose())
    radius = resolve_cutting_profile(_radius_mill())
    assert profile_undercuts(thread)
    assert profile_undercuts(lolli)
    assert not profile_undercuts(flat)
    assert not profile_undercuts(vbit)
    assert not profile_undercuts(ball)
    assert not profile_undercuts(bull)
    assert not profile_undercuts(radius)


def test_auto_3axis_vbit_heightmap():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=False,
        tool_table={1: _vbit()},
    )
    assert rec.backend == BACKEND_HEIGHTMAP
    assert BACKEND_HEIGHTMAP in rec.allowed
    assert BACKEND_VOXEL in rec.allowed
    assert BACKEND_CYLINDRICAL not in rec.allowed
    assert not rec.has_4axis
    assert not rec.accuracy_tradeoff


def test_auto_4axis_cylindrical():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=True,
        tool_table={1: _flat_tool()},
    )
    assert rec.has_4axis
    assert not rec.has_off_axis_y
    assert rec.backend == BACKEND_CYLINDRICAL
    assert BACKEND_HEIGHTMAP not in rec.allowed


def test_auto_4axis_off_axis_y_voxels():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=True,
        has_off_axis_y=True,
        tool_table={1: _flat_tool()},
    )
    assert rec.has_off_axis_y
    assert rec.backend == BACKEND_VOXEL
    assert BACKEND_CYLINDRICAL in rec.allowed
    assert BACKEND_HEIGHTMAP not in rec.allowed


def test_auto_3axis_off_axis_y_still_heightmap():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=False,
        has_off_axis_y=True,
        tool_table={1: _flat_tool()},
    )
    assert rec.backend == BACKEND_HEIGHTMAP


def test_undercut_wins_over_wrapping():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=True,
        has_off_axis_y=False,
        tool_table={1: _lollipop()},
    )
    assert rec.has_undercut
    assert rec.backend == BACKEND_VOXEL


def test_cylindrical_override_on_index_job():
    rec = recommend_carver(
        mode=MODE_CYLINDRICAL,
        has_4axis=True,
        has_off_axis_y=True,
        tool_table={1: _flat_tool()},
    )
    assert rec.recommended == BACKEND_VOXEL
    assert rec.backend == BACKEND_CYLINDRICAL


def test_thread_mill_recommends_heightmap():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=False,
        tool_table={1: _thread_mill()},
    )
    assert not rec.has_undercut
    assert rec.backend == BACKEND_HEIGHTMAP
    assert BACKEND_HEIGHTMAP in rec.allowed
    assert BACKEND_VOXEL in rec.allowed
    assert not rec.accuracy_tradeoff


def test_thread_mill_4axis_recommends_cylindrical():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=True,
        tool_table={1: _thread_mill()},
    )
    assert not rec.has_undercut
    assert rec.backend == BACKEND_CYLINDRICAL
    assert BACKEND_VOXEL in rec.allowed


def test_thread_mill_with_lollipop_recommends_voxel():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=False,
        tool_table={1: _thread_mill(), 2: _lollipop()},
    )
    assert rec.has_undercut
    assert rec.backend == BACKEND_VOXEL


def test_lollipop_recommends_voxel():
    rec = recommend_carver(
        mode=MODE_AUTO,
        has_4axis=False,
        tool_table={1: _lollipop()},
    )
    assert rec.backend == BACKEND_VOXEL


def test_heightmap_on_4axis_rejected():
    rec = recommend_carver(
        mode=MODE_HEIGHTMAP,
        has_4axis=True,
        tool_table={1: _flat_tool()},
    )
    assert rec.backend == BACKEND_CYLINDRICAL
    assert BACKEND_HEIGHTMAP not in rec.allowed
