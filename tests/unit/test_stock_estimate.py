"""Unit tests for toolpath-based rectangular stock estimation."""

import pytest

from carveracontroller.addons.cam.metadata import CamStock
from carveracontroller.addons.stock.stock_defaults import (
    DEFAULT_HEIGHT_MM,
    DEFAULT_LENGTH_MM,
    DEFAULT_WIDTH_MM,
)
from carveracontroller.addons.stock.stock_estimate import (
    auto_stock_for_loaded_file,
    estimate_rectangular_stock,
    estimate_rotary_stock,
    header_stock_usable,
    max_cutting_tool_diameter_mm,
    shape_and_origin_from_cam_stock,
)
from carveracontroller.addons.stock.stock_geometry import compute_wcs_bounds
from carveracontroller.addons.stock.stock_origin import CORNER_BL, CORNER_LC, Z_CENTER, Z_TOP
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RectangularStock, RotaryCylindricalStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition
from carveracontroller.CNC import LASER_TOOL_NUMBER, PROBE_TOOLS_RANGE_START, ZPROBE_TOOL_NUMBER


def test_estimate_pads_xy_by_tool_radius():
    # 6 mm tool → 3 mm pad each side; cutting 3..97 x 3..47, Z -10..-0.5
    result = estimate_rectangular_stock(3.0, 3.0, -10.0, 97.0, 47.0, -0.5, pad_xy_mm=3.0)
    assert result is not None
    shape, origin = result

    assert isinstance(shape, RectangularStock)
    assert shape.width_mm == pytest.approx(100.0)
    assert shape.length_mm == pytest.approx(50.0)
    assert shape.height_mm == pytest.approx(10.0)
    assert origin.xy_corner == CORNER_BL
    assert origin.z_reference == Z_TOP
    assert origin.offset_x_mm == pytest.approx(0.0)
    assert origin.offset_y_mm == pytest.approx(0.0)
    assert origin.offset_z_mm == pytest.approx(0.0)

    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_x == pytest.approx(0.0)
    assert bounds.max_x == pytest.approx(100.0)
    assert bounds.min_y == pytest.approx(0.0)
    assert bounds.max_y == pytest.approx(50.0)
    assert bounds.min_z == pytest.approx(-10.0)
    assert bounds.max_z == pytest.approx(0.0)


def test_estimate_includes_wcs_zero_when_cuts_are_below_top():
    shape, origin = estimate_rectangular_stock(0.0, 0.0, -5.0, 10.0, 10.0, -0.2, pad_xy_mm=0.0)
    assert origin.offset_z_mm == pytest.approx(0.0)
    assert shape.height_mm == pytest.approx(5.0)
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_z == pytest.approx(-5.0)
    assert bounds.max_z == pytest.approx(0.0)


def test_estimate_spans_cuts_above_and_below_zero():
    shape, origin = estimate_rectangular_stock(0.0, 0.0, -5.0, 10.0, 8.0, 2.0, pad_xy_mm=0.0)
    assert origin.offset_z_mm == pytest.approx(2.0)
    assert shape.height_mm == pytest.approx(7.0)
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_z == pytest.approx(-5.0)
    assert bounds.max_z == pytest.approx(2.0)


def test_estimate_returns_none_for_empty_aabb():
    # CNC.resetMargins starts with xmin > xmax
    assert estimate_rectangular_stock(1000000.0, 1000000.0, 1000000.0, -1000000.0, -1000000.0, -1000000.0) is None


def test_estimate_degenerate_xy_uses_padding_and_epsilon():
    shape, origin = estimate_rectangular_stock(5.0, 5.0, 0.0, 5.0, 5.0, 0.0, pad_xy_mm=3.0)
    assert shape.width_mm == pytest.approx(6.0)
    assert shape.length_mm == pytest.approx(6.0)
    assert shape.height_mm == pytest.approx(1.0)
    assert origin.offset_x_mm == pytest.approx(2.0)
    assert origin.offset_y_mm == pytest.approx(2.0)


def test_estimate_planar_job_uses_minimum_one_mm_height():
    # Laser / engraving at Z=0: no vertical span, still guess 1 mm stock.
    shape, origin = estimate_rectangular_stock(0.0, 0.0, 0.0, 50.0, 30.0, 0.0, pad_xy_mm=0.0)
    assert shape.width_mm == pytest.approx(50.0)
    assert shape.length_mm == pytest.approx(30.0)
    assert shape.height_mm == pytest.approx(1.0)
    assert origin.offset_z_mm == pytest.approx(0.0)
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_z == pytest.approx(-1.0)
    assert bounds.max_z == pytest.approx(0.0)


def test_estimate_zero_span_uses_minimum_one_mm():
    shape, origin = estimate_rectangular_stock(5.0, 5.0, 0.0, 5.0, 5.0, 0.0, pad_xy_mm=0.0)
    assert shape.width_mm == pytest.approx(1.0)
    assert shape.length_mm == pytest.approx(1.0)
    assert shape.height_mm == pytest.approx(1.0)


def test_estimate_negative_pad_is_treated_as_zero():
    shape, origin = estimate_rectangular_stock(1.0, 2.0, -1.0, 4.0, 6.0, 0.0, pad_xy_mm=-2.0)
    assert shape.width_mm == pytest.approx(3.0)
    assert shape.length_mm == pytest.approx(4.0)
    assert origin.offset_x_mm == pytest.approx(1.0)
    assert origin.offset_y_mm == pytest.approx(2.0)


def test_estimate_rounds_outward_to_whole_mm():
    shape, origin = estimate_rectangular_stock(1.234, 2.345, -5.678, 10.678, 8.901, 0.123, pad_xy_mm=0.0)
    assert origin.offset_x_mm == pytest.approx(1.0)
    assert origin.offset_y_mm == pytest.approx(2.0)
    assert origin.offset_z_mm == pytest.approx(1.0)
    assert shape.width_mm == pytest.approx(10.0)  # 11 - 1
    assert shape.length_mm == pytest.approx(7.0)  # 9 - 2
    assert shape.height_mm == pytest.approx(7.0)  # 1 - (-6)

    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_x <= 1.234
    assert bounds.max_x >= 10.678
    assert bounds.min_y <= 2.345
    assert bounds.max_y >= 8.901
    assert bounds.min_z <= -5.678
    assert bounds.max_z >= 0.123


def test_max_cutting_tool_diameter_skips_probe_and_laser():
    table = {
        1: ToolDefinition(number=1, diameter=6.0),
        2: ToolDefinition(number=2, diameter=3.0),
        ZPROBE_TOOL_NUMBER: ToolDefinition(number=ZPROBE_TOOL_NUMBER, diameter=99.0),
        LASER_TOOL_NUMBER: ToolDefinition(number=LASER_TOOL_NUMBER, diameter=88.0),
        PROBE_TOOLS_RANGE_START: ToolDefinition(number=PROBE_TOOLS_RANGE_START, diameter=77.0),
    }
    assert max_cutting_tool_diameter_mm(table) == pytest.approx(6.0)


def test_max_cutting_tool_diameter_applies_inch_scale():
    table = {1: ToolDefinition(number=1, diameter=0.25)}
    assert max_cutting_tool_diameter_mm(table, unit_scale=25.4) == pytest.approx(6.35)


def test_max_cutting_tool_diameter_empty_or_missing():
    assert max_cutting_tool_diameter_mm({}) == 0.0
    assert max_cutting_tool_diameter_mm({1: ToolDefinition(number=1, diameter=None)}) == 0.0
    assert max_cutting_tool_diameter_mm({1: ToolDefinition(number=1, diameter=-3.0)}) == 0.0


def test_header_stock_usable():
    assert header_stock_usable(None) is False
    assert header_stock_usable(CamStock(kind="rectangular")) is False
    cam = CamStock(kind="rectangular", width_mm=120.0, length_mm=80.0, height_mm=12.0)
    assert header_stock_usable(cam) is True


def test_auto_stock_prefers_cam_header():
    cam = CamStock(kind="rectangular", width_mm=120.0, length_mm=80.0, height_mm=12.0, offset_x_mm=1.0)
    shape, origin = auto_stock_for_loaded_file(cam, 0.0, 0.0, -1.0, 10.0, 10.0, 0.0, tool_table={})
    assert isinstance(shape, RectangularStock)
    assert shape.width_mm == pytest.approx(120.0)
    assert shape.length_mm == pytest.approx(80.0)
    assert origin.offset_x_mm == pytest.approx(1.0)


def test_auto_stock_does_not_rescale_header_already_in_mm():
    cam = CamStock(kind="rectangular", width_mm=120.0, length_mm=80.0, height_mm=12.0, offset_x_mm=1.0)
    shape, origin = auto_stock_for_loaded_file(cam, 0.0, 0.0, -1.0, 10.0, 10.0, 0.0, tool_table={}, unit_scale=25.4)
    assert shape.width_mm == pytest.approx(120.0)
    assert origin.offset_x_mm == pytest.approx(1.0)


def test_auto_stock_estimates_when_header_stock_missing():
    table = {1: ToolDefinition(number=1, diameter=6.0)}
    shape, origin = auto_stock_for_loaded_file(
        None, 3.0, 3.0, -10.0, 97.0, 47.0, -0.5, tool_table=table, unit_scale=1.0
    )
    assert shape.width_mm == pytest.approx(100.0)
    assert origin.offset_x_mm == pytest.approx(0.0)


def test_auto_stock_defaults_when_path_has_no_cuts():
    shape, origin = auto_stock_for_loaded_file(
        None, 1000000.0, 1000000.0, 1000000.0, -1000000.0, -1000000.0, -1000000.0
    )
    assert shape.width_mm == pytest.approx(DEFAULT_WIDTH_MM)
    assert shape.length_mm == pytest.approx(DEFAULT_LENGTH_MM)
    assert shape.height_mm == pytest.approx(DEFAULT_HEIGHT_MM)
    assert origin.offset_x_mm == pytest.approx(0.0)


def test_auto_stock_invalid_cam_falls_back_to_estimate():
    cam = CamStock(kind="rectangular")  # missing dimensions
    table = {1: ToolDefinition(number=1, diameter=6.0)}
    shape, origin = auto_stock_for_loaded_file(cam, 3.0, 3.0, -10.0, 97.0, 47.0, -0.5, tool_table=table)
    assert shape.width_mm == pytest.approx(100.0)
    assert origin.offset_x_mm == pytest.approx(0.0)


def test_auto_stock_caps_zmax_with_height_scheme_bound():
    shape, origin = auto_stock_for_loaded_file(
        None,
        0.0,
        0.0,
        -10.0,
        10.0,
        10.0,
        15.0,
        feed_z_max_mm=-0.5,
    )
    # Top stays at WCS 0 (CAM Z0=top); height is cutting depth, not clearance.
    assert origin.offset_z_mm == pytest.approx(0.0)
    assert shape.height_mm == pytest.approx(10.0)


def test_auto_stock_does_not_inflate_when_height_bound_is_above_cnc_zmax():
    # Viewer dummy range is z_min+1 when all feed Z is identical; do not grow stock.
    shape, origin = auto_stock_for_loaded_file(
        None,
        0.0,
        0.0,
        -5.0,
        10.0,
        10.0,
        -0.5,
        feed_z_max_mm=0.5,
    )
    assert origin.offset_z_mm == pytest.approx(0.0)
    assert shape.height_mm == pytest.approx(5.0)


def test_shape_and_origin_from_cam_cylindrical():
    cam = CamStock(kind="cylindrical", diameter_mm=50.0, height_mm=15.0, xy_corner="center", z_reference="bottom")
    shape, origin = shape_and_origin_from_cam_stock(cam)
    assert isinstance(shape, CylindricalStock)
    assert shape.diameter_mm == pytest.approx(50.0)
    assert origin.xy_corner == "center"
    assert origin.z_reference == "bottom"


def test_shape_and_origin_from_cam_rotary_cylindrical():
    cam = CamStock(
        kind="rotary_cylindrical",
        diameter_mm=30.0,
        length_mm=100.0,
        xy_corner="lc",
        z_reference="center",
    )
    shape, origin = shape_and_origin_from_cam_stock(cam)
    assert isinstance(shape, RotaryCylindricalStock)
    assert shape.diameter_mm == pytest.approx(30.0)
    assert shape.length_mm == pytest.approx(100.0)
    assert origin.xy_corner == "lc"
    assert origin.z_reference == "center"


def test_estimate_rotary_cylinder_mirrors_about_axis():
    # Wrapping: Y=0, feed Z 10..22, X 6..74. Far side is never visited.
    result = estimate_rotary_stock(6.0, 0.0, 10.0, 74.0, 0.0, 22.0, pad_xy_mm=0.0)
    assert result is not None
    shape, origin = result
    assert isinstance(shape, RotaryCylindricalStock)
    assert origin.z_reference == Z_CENTER
    assert origin.xy_corner == CORNER_LC
    assert origin.offset_x_mm == pytest.approx(6.0)
    assert origin.offset_y_mm == pytest.approx(0.0)
    assert origin.offset_z_mm == pytest.approx(0.0)
    assert shape.length_mm == pytest.approx(68.0)
    assert shape.diameter_mm == pytest.approx(44.0)
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_z == pytest.approx(-22.0)
    assert bounds.max_z == pytest.approx(22.0)
    assert bounds.min_y == pytest.approx(-22.0)
    assert bounds.max_y == pytest.approx(22.0)


def test_estimate_rotary_rectangular_square_when_y_is_zero():
    shape, origin = estimate_rotary_stock(0.0, 0.0, 5.0, 50.0, 0.0, 20.0, pad_xy_mm=0.0, kind="rectangular")
    assert isinstance(shape, RectangularStock)
    assert origin.z_reference == Z_CENTER
    assert shape.width_mm == pytest.approx(50.0)
    assert shape.height_mm == pytest.approx(40.0)
    assert shape.length_mm == pytest.approx(40.0)  # square from Z when Y≈0
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_z == pytest.approx(-20.0)
    assert bounds.max_z == pytest.approx(20.0)


def test_auto_stock_rotary_uses_feed_z_cap():
    shape, origin = auto_stock_for_loaded_file(
        None,
        0.0,
        0.0,
        10.0,
        80.0,
        0.0,
        30.0,
        feed_z_max_mm=22.0,
        rotary=True,
    )
    assert isinstance(shape, RotaryCylindricalStock)
    assert origin.z_reference == Z_CENTER
    assert shape.diameter_mm == pytest.approx(44.0)
