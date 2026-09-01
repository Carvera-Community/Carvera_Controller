"""Unit tests for stock geometry (shape + origin → WCS AABB)."""

import pytest

from carveracontroller.addons.stock.stock_defaults import (
    DEFAULT_HEIGHT_MM,
    DEFAULT_LENGTH_MM,
    DEFAULT_WIDTH_MM,
    bounds_from_settings,
    default_bounds,
    default_settings,
)
from carveracontroller.addons.stock.stock_geometry import compute_wcs_bounds, contains_wcs
from carveracontroller.addons.stock.stock_origin import (
    CORNER_BC,
    CORNER_BL,
    CORNER_BR,
    CORNER_CENTER,
    CORNER_FC,
    CORNER_LC,
    CORNER_RC,
    CORNER_TL,
    CORNER_TR,
    Z_BOTTOM,
    Z_CENTER,
    Z_TOP,
    StockOrigin,
    named_origin_relative_to_center,
)
from carveracontroller.addons.stock.stock_shape import (
    CylindricalStock,
    RectangularStock,
    RotaryCylindricalStock,
    shape_from_dict,
)


def test_rectangular_local_bounds():
    stock = RectangularStock(width_mm=50, length_mm=40, height_mm=10)
    assert stock.local_bounds() == ((0.0, 0.0, 0.0), (50.0, 40.0, 10.0))


def test_rectangular_rejects_non_positive():
    with pytest.raises(ValueError):
        RectangularStock(width_mm=0, length_mm=10, height_mm=10)


def test_rectangular_contains_local():
    stock = RectangularStock(width_mm=50, length_mm=40, height_mm=10)
    assert stock.contains_local(25, 20, 5)
    assert not stock.contains_local(-0.1, 20, 5)
    assert not stock.contains_local(25, 40.1, 5)


def test_cylindrical_local_bounds():
    stock = CylindricalStock(diameter_mm=50, height_mm=10)
    assert stock.local_bounds() == ((0.0, 0.0, 0.0), (50.0, 50.0, 10.0))


def test_cylindrical_rejects_non_positive():
    with pytest.raises(ValueError):
        CylindricalStock(diameter_mm=0, height_mm=10)
    with pytest.raises(ValueError):
        CylindricalStock(diameter_mm=10, height_mm=-1)


def test_cylindrical_contains_local():
    stock = CylindricalStock(diameter_mm=50, height_mm=10)
    assert stock.contains_local(25, 25, 5)  # axis
    assert stock.contains_local(25 + 24.9, 25, 5)  # near rim
    assert not stock.contains_local(0, 0, 5)  # AABB corner
    assert not stock.contains_local(25, 25, -0.1)
    assert not stock.contains_local(25, 25, 10.1)


@pytest.mark.parametrize(
    "corner,expected_xy",
    [
        (CORNER_BL, (0.0, 0.0, 50.0, 40.0)),
        (CORNER_FC, (-25.0, 0.0, 25.0, 40.0)),
        (CORNER_BR, (-50.0, 0.0, 0.0, 40.0)),
        (CORNER_LC, (0.0, -20.0, 50.0, 20.0)),
        (CORNER_CENTER, (-25.0, -20.0, 25.0, 20.0)),
        (CORNER_RC, (-50.0, -20.0, 0.0, 20.0)),
        (CORNER_TL, (0.0, -40.0, 50.0, 0.0)),
        (CORNER_BC, (-25.0, -40.0, 25.0, 0.0)),
        (CORNER_TR, (-50.0, -40.0, 0.0, 0.0)),
    ],
)
def test_wcs_bounds_xy_corners(corner, expected_xy):
    shape = RectangularStock(50, 40, 10)
    origin = StockOrigin(xy_corner=corner, z_reference=Z_TOP)
    bounds = compute_wcs_bounds(shape, origin)
    assert (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y) == expected_xy
    assert bounds.min_z == -10.0
    assert bounds.max_z == 0.0


def test_wcs_bounds_z_bottom():
    shape = RectangularStock(20, 30, 8)
    origin = StockOrigin(xy_corner=CORNER_BL, z_reference=Z_BOTTOM)
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_z == 0.0
    assert bounds.max_z == 8.0


def test_cylindrical_wcs_bounds_center_top():
    shape = CylindricalStock(diameter_mm=40, height_mm=12)
    origin = StockOrigin(xy_corner=CORNER_CENTER, z_reference=Z_TOP)
    bounds = compute_wcs_bounds(shape, origin)
    assert (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y) == (-20.0, -20.0, 20.0, 20.0)
    assert bounds.min_z == -12.0
    assert bounds.max_z == 0.0
    assert contains_wcs(shape, bounds, 0.0, 0.0, -6.0)
    assert not contains_wcs(shape, bounds, 19.0, 19.0, -6.0)


def test_cylindrical_wcs_bounds_bl_bottom():
    shape = CylindricalStock(diameter_mm=30, height_mm=8)
    origin = StockOrigin(xy_corner=CORNER_BL, z_reference=Z_BOTTOM)
    bounds = compute_wcs_bounds(shape, origin)
    assert (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y) == (0.0, 0.0, 30.0, 30.0)
    assert bounds.min_z == 0.0
    assert bounds.max_z == 8.0
    assert contains_wcs(shape, bounds, 15.0, 15.0, 4.0)
    assert not contains_wcs(shape, bounds, 0.5, 0.5, 4.0)


def test_shape_roundtrip_dict():
    shape = RectangularStock(12.5, 33, 4)
    restored = shape_from_dict(shape.to_dict())
    assert isinstance(restored, RectangularStock)
    assert restored.width_mm == 12.5
    assert restored.length_mm == 33
    assert restored.height_mm == 4


def test_cylindrical_roundtrip_dict():
    shape = CylindricalStock(diameter_mm=42.5, height_mm=9)
    restored = shape_from_dict(shape.to_dict())
    assert isinstance(restored, CylindricalStock)
    assert restored.diameter_mm == 42.5
    assert restored.height_mm == 9


def test_wcs_bounds_applies_xyz_offsets():
    shape = RectangularStock(50, 40, 10)
    origin = StockOrigin(
        xy_corner=CORNER_BL,
        z_reference=Z_TOP,
        offset_x_mm=5.0,
        offset_y_mm=-2.5,
        offset_z_mm=1.0,
    )
    bounds = compute_wcs_bounds(shape, origin)
    assert (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y) == (5.0, -2.5, 55.0, 37.5)
    assert bounds.min_z == -9.0
    assert bounds.max_z == 1.0


def test_origin_roundtrip_dict_includes_offsets():
    origin = StockOrigin(
        xy_corner=CORNER_TR,
        z_reference=Z_BOTTOM,
        offset_x_mm=-1.5,
        offset_y_mm=0.0,
        offset_z_mm=3.25,
    )
    restored = StockOrigin.from_dict(origin.to_dict())
    assert restored.xy_corner == CORNER_TR
    assert restored.z_reference == Z_BOTTOM
    assert restored.offset_x_mm == -1.5
    assert restored.offset_y_mm == 0.0
    assert restored.offset_z_mm == 3.25


def test_origin_from_dict_defaults_missing_offsets():
    origin = StockOrigin.from_dict({"xy_corner": "BL", "z_reference": "top"})
    assert origin.offset_x_mm == 0.0
    assert origin.offset_y_mm == 0.0
    assert origin.offset_z_mm == 0.0


def test_origin_rejects_non_finite_offsets():
    with pytest.raises(ValueError, match="offset_x_mm"):
        StockOrigin(offset_x_mm=float("nan"))
    with pytest.raises(ValueError, match="offset_z_mm"):
        StockOrigin(offset_z_mm=float("inf"))


def test_origin_normalizes_case():
    origin = StockOrigin(xy_corner="BL", z_reference="Top")
    assert origin.xy_corner == CORNER_BL
    assert origin.z_reference == Z_TOP


def test_default_bounds_matches_defaults():
    bounds = default_bounds()
    assert bounds.min_x == 0.0
    assert bounds.min_y == 0.0
    assert bounds.max_x == DEFAULT_WIDTH_MM
    assert bounds.max_y == DEFAULT_LENGTH_MM
    assert bounds.min_z == -DEFAULT_HEIGHT_MM
    assert bounds.max_z == 0.0


def test_bounds_from_settings():
    settings = default_settings()
    settings["shape"] = RectangularStock(50, 40, 10).to_dict()
    settings["origin"] = StockOrigin(
        xy_corner=CORNER_BR,
        z_reference=Z_BOTTOM,
        offset_x_mm=10.0,
        offset_y_mm=-5.0,
        offset_z_mm=2.0,
    ).to_dict()
    bounds = bounds_from_settings(settings)
    assert (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y) == (-40.0, -5.0, 10.0, 35.0)
    assert bounds.min_z == 2.0
    assert bounds.max_z == 12.0


def test_bounds_from_cylindrical_settings():
    settings = default_settings()
    settings["shape"] = CylindricalStock(diameter_mm=50, height_mm=10).to_dict()
    settings["origin"] = StockOrigin(xy_corner=CORNER_CENTER, z_reference=Z_TOP).to_dict()
    bounds = bounds_from_settings(settings)
    assert (bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y) == (-25.0, -25.0, 25.0, 25.0)
    assert bounds.min_z == -10.0
    assert bounds.max_z == 0.0


def test_wcs_bounds_bl_center_is_front_left_mid_z():
    shape = RectangularStock(80, 40, 20)
    origin = StockOrigin(xy_corner=CORNER_BL, z_reference=Z_CENTER)
    bounds = compute_wcs_bounds(shape, origin)
    assert (bounds.min_x, bounds.max_x) == (0.0, 80.0)
    assert bounds.min_y == pytest.approx(0.0)
    assert bounds.max_y == pytest.approx(40.0)
    assert bounds.min_z == pytest.approx(-10.0)
    assert bounds.max_z == pytest.approx(10.0)


def test_wcs_bounds_lc_center_is_left_face_center():
    shape = RectangularStock(80, 40, 20)
    origin = StockOrigin(xy_corner=CORNER_LC, z_reference=Z_CENTER)
    bounds = compute_wcs_bounds(shape, origin)
    assert (bounds.min_x, bounds.max_x) == (0.0, 80.0)
    assert bounds.min_y == pytest.approx(-20.0)
    assert bounds.max_y == pytest.approx(20.0)
    assert bounds.min_z == pytest.approx(-10.0)
    assert bounds.max_z == pytest.approx(10.0)


@pytest.mark.parametrize(
    "xy_corner,z_reference,expected",
    [
        (CORNER_BL, Z_TOP, (0.0, 0.0, -20.0, 80.0, 40.0, 0.0)),
        (CORNER_BL, Z_CENTER, (0.0, 0.0, -10.0, 80.0, 40.0, 10.0)),
        (CORNER_BL, Z_BOTTOM, (0.0, 0.0, 0.0, 80.0, 40.0, 20.0)),
        (CORNER_FC, Z_TOP, (-40.0, 0.0, -20.0, 40.0, 40.0, 0.0)),
        (CORNER_FC, Z_CENTER, (-40.0, 0.0, -10.0, 40.0, 40.0, 10.0)),
        (CORNER_FC, Z_BOTTOM, (-40.0, 0.0, 0.0, 40.0, 40.0, 20.0)),
        (CORNER_BR, Z_TOP, (-80.0, 0.0, -20.0, 0.0, 40.0, 0.0)),
        (CORNER_BR, Z_CENTER, (-80.0, 0.0, -10.0, 0.0, 40.0, 10.0)),
        (CORNER_BR, Z_BOTTOM, (-80.0, 0.0, 0.0, 0.0, 40.0, 20.0)),
        (CORNER_LC, Z_TOP, (0.0, -20.0, -20.0, 80.0, 20.0, 0.0)),
        (CORNER_LC, Z_CENTER, (0.0, -20.0, -10.0, 80.0, 20.0, 10.0)),
        (CORNER_LC, Z_BOTTOM, (0.0, -20.0, 0.0, 80.0, 20.0, 20.0)),
        (CORNER_CENTER, Z_TOP, (-40.0, -20.0, -20.0, 40.0, 20.0, 0.0)),
        (CORNER_CENTER, Z_CENTER, (-40.0, -20.0, -10.0, 40.0, 20.0, 10.0)),
        (CORNER_CENTER, Z_BOTTOM, (-40.0, -20.0, 0.0, 40.0, 20.0, 20.0)),
        (CORNER_RC, Z_TOP, (-80.0, -20.0, -20.0, 0.0, 20.0, 0.0)),
        (CORNER_RC, Z_CENTER, (-80.0, -20.0, -10.0, 0.0, 20.0, 10.0)),
        (CORNER_RC, Z_BOTTOM, (-80.0, -20.0, 0.0, 0.0, 20.0, 20.0)),
        (CORNER_TL, Z_TOP, (0.0, -40.0, -20.0, 80.0, 0.0, 0.0)),
        (CORNER_TL, Z_CENTER, (0.0, -40.0, -10.0, 80.0, 0.0, 10.0)),
        (CORNER_TL, Z_BOTTOM, (0.0, -40.0, 0.0, 80.0, 0.0, 20.0)),
        (CORNER_BC, Z_TOP, (-40.0, -40.0, -20.0, 40.0, 0.0, 0.0)),
        (CORNER_BC, Z_CENTER, (-40.0, -40.0, -10.0, 40.0, 0.0, 10.0)),
        (CORNER_BC, Z_BOTTOM, (-40.0, -40.0, 0.0, 40.0, 0.0, 20.0)),
        (CORNER_TR, Z_TOP, (-80.0, -40.0, -20.0, 0.0, 0.0, 0.0)),
        (CORNER_TR, Z_CENTER, (-80.0, -40.0, -10.0, 0.0, 0.0, 10.0)),
        (CORNER_TR, Z_BOTTOM, (-80.0, -40.0, 0.0, 0.0, 0.0, 20.0)),
    ],
)
def test_wcs_bounds_nine_by_three_grid(xy_corner, z_reference, expected):
    shape = RectangularStock(80, 40, 20)
    origin = StockOrigin(xy_corner=xy_corner, z_reference=z_reference)
    bounds = compute_wcs_bounds(shape, origin)
    assert (
        bounds.min_x,
        bounds.min_y,
        bounds.min_z,
        bounds.max_x,
        bounds.max_y,
        bounds.max_z,
    ) == pytest.approx(expected)


def test_named_origin_left_center_matches_header():
    assert named_origin_relative_to_center(220, 30, 20, CORNER_LC, Z_CENTER) == pytest.approx((-110.0, 0.0, 0.0))
    assert named_origin_relative_to_center(220, 30, 20, CORNER_BL, Z_CENTER) == pytest.approx((-110.0, -15.0, 0.0))


def test_rotary_cylinder_wcs_bounds_on_axis():
    shape = RotaryCylindricalStock(diameter_mm=44, length_mm=70)
    origin = StockOrigin(xy_corner=CORNER_LC, z_reference=Z_CENTER, offset_x_mm=6.0)
    bounds = compute_wcs_bounds(shape, origin)
    assert bounds.min_x == pytest.approx(6.0)
    assert bounds.max_x == pytest.approx(76.0)
    assert bounds.min_y == pytest.approx(-22.0)
    assert bounds.max_y == pytest.approx(22.0)
    assert bounds.min_z == pytest.approx(-22.0)
    assert bounds.max_z == pytest.approx(22.0)
    assert contains_wcs(shape, bounds, 10.0, 0.0, 0.0)
    assert contains_wcs(shape, bounds, 10.0, 0.0, 21.0)
    assert not contains_wcs(shape, bounds, 10.0, 21.0, 21.0)


def test_rotary_cylinder_roundtrip_dict():
    shape = RotaryCylindricalStock(diameter_mm=30.5, length_mm=120)
    restored = shape_from_dict(shape.to_dict())
    assert isinstance(restored, RotaryCylindricalStock)
    assert restored.diameter_mm == 30.5
    assert restored.length_mm == 120


def test_rotate_yz_quarter_turn():
    from carveracontroller.addons.stock.stock_geometry import rotate_yz

    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert y == pytest.approx(-10.0)
    assert z == pytest.approx(0.0)


def test_stock_theta_is_atan2_minus_a():
    from carveracontroller.addons.stock.stock_geometry import rotate_yz, stock_theta_deg

    assert stock_theta_deg(0.0, 14.0, 0.0) == pytest.approx(0.0)
    # Tool on +Z at A=90 hits stock θ=-90, the same side mill clears.
    assert stock_theta_deg(0.0, 14.0, 90.0) == pytest.approx(-90.0)
    y, z = rotate_yz(0.0, 14.0, 90.0)
    assert stock_theta_deg(y, z, 0.0) == pytest.approx(-90.0)
