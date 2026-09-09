"""Regression tests for rotary viewer transforms."""

from pathlib import Path

import pytest

from carveracontroller.GcodeViewer import (
    rotate_mat_by_x_axis_angle,
    rotate_point_then_center,
    rotate_pt_by_x_axis_angle,
)


def test_rotary_pointer_rotates_around_wcs_origin_before_centering():
    center = [0.0, 4.0, -2.0]
    point = rotate_pt_by_x_axis_angle(0.0, 0.0, 10.0, 120.0)
    inverse_rotation = rotate_mat_by_x_axis_angle(-120.0)

    displayed = rotate_point_then_center(point, center, inverse_rotation)

    assert displayed == pytest.approx([0.0, -4.0, 12.0])


def test_toolpath_shader_rotates_before_centering():
    shader = (Path(__file__).parents[2] / "carveracontroller" / "shaders" / "toolpath.glsl").read_text()

    assert "center_offset * rotation_mat * world_pos" in shader
    assert "rotation_mat * center_offset * world_pos" not in shader
