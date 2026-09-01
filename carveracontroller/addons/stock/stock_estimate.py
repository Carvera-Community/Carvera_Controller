"""Estimate rectangular stock from cutting-move bounds when CAM headers omit it."""

from __future__ import annotations

import math

from carveracontroller.addons.cam.metadata import CamStock
from carveracontroller.CNC import (
    LASER_TOOL_NUMBER,
    ZPROBE_TOOL_NUMBER,
    is_probe_tools_range,
)

from .stock_defaults import default_origin, default_rotary_origin, default_rotary_shape, default_shape
from .stock_origin import CORNER_BL, CORNER_LC, Z_CENTER, Z_TOP, StockOrigin
from .stock_shape import RectangularStock, RotaryCylindricalStock, StockShape, shape_from_dict

# Guessed extents snap to whole millimetres
# Keep at least 1 mm for planar jobs (eg. laser engraving)
_MIN_EXTENT_MM = 1.0
_NEAR_ZERO_MM = 1e-6


def _is_cutting_tool_number(number: int) -> bool:
    if number in (LASER_TOOL_NUMBER, ZPROBE_TOOL_NUMBER):
        return False
    return not is_probe_tools_range(number)


def max_cutting_tool_diameter_mm(tool_table: dict, unit_scale: float = 1.0) -> float:
    """Largest positive cutting diameter in *tool_table*, converted to millimetres."""
    scale = float(unit_scale) if unit_scale else 1.0
    max_diameter = 0.0
    for number, tool_def in (tool_table or {}).items():
        try:
            tool_number = int(number)
        except (TypeError, ValueError):
            continue
        if not _is_cutting_tool_number(tool_number):
            continue
        diameter = getattr(tool_def, "diameter", None)
        try:
            diameter_mm = float(diameter) * scale
        except (TypeError, ValueError):
            continue
        if diameter_mm > max_diameter:
            max_diameter = diameter_mm
    return max_diameter


def estimate_rectangular_stock(
    xmin: float,
    ymin: float,
    zmin: float,
    xmax: float,
    ymax: float,
    zmax: float,
    pad_xy_mm: float = 0.0,
) -> tuple[RectangularStock, StockOrigin] | None:
    """Build BL / Z-top stock around a cutting AABB, padded in XY by *pad_xy_mm*.

    Extents are snapped outward to whole millimetres so noisy G-code
    coordinates still fit and the settings fields stay readable.

    Returns ``None`` when the AABB is empty (no cutting moves).
    """
    if xmin > xmax or ymin > ymax or zmin > zmax:
        return None

    pad = max(float(pad_xy_mm), 0.0)
    min_x = math.floor(xmin - pad)
    min_y = math.floor(ymin - pad)
    max_x = math.ceil(xmax + pad)
    max_y = math.ceil(ymax + pad)
    # Z0 = top: expand the top upward and the bottom downward.
    max_z = math.ceil(max(zmax, 0.0))
    min_z = math.floor(min(zmin, 0.0))

    width = max(max_x - min_x, _MIN_EXTENT_MM)
    length = max(max_y - min_y, _MIN_EXTENT_MM)
    height = max(max_z - min_z, _MIN_EXTENT_MM)

    shape = RectangularStock(width_mm=width, length_mm=length, height_mm=height)
    origin = StockOrigin(
        xy_corner=CORNER_BL,
        z_reference=Z_TOP,
        offset_x_mm=min_x,
        offset_y_mm=min_y,
        offset_z_mm=max_z,
    )
    return shape, origin


def estimate_rotary_stock(
    xmin: float,
    ymin: float,
    zmin: float,
    xmax: float,
    ymax: float,
    zmax: float,
    pad_xy_mm: float = 0.0,
    *,
    kind: str = RotaryCylindricalStock.kind,
) -> tuple[StockShape, StockOrigin] | None:
    """Build axis-centered rotary stock, mirrored about Y=Z=0.

    Cutting Z is typically the +Z (top) side of the bar; the far side is
    assumed symmetric about the A axis. Extents snap outward to whole millimetres.

    Returns ``None`` when the AABB is empty (no cutting moves).
    """
    if xmin > xmax or ymin > ymax or zmin > zmax:
        return None

    pad = max(float(pad_xy_mm), 0.0)
    min_x = math.floor(xmin - pad)
    max_x = math.ceil(xmax + pad)
    length = max(max_x - min_x, _MIN_EXTENT_MM)

    max_abs_y = max(abs(ymin), abs(ymax))
    max_abs_z = max(abs(zmin), abs(zmax))
    # Radial pad (tool radius) so the bar encloses the cutter at the surface.
    radius = math.hypot(max_abs_y, max_abs_z) + pad
    diameter = max(2.0 * math.ceil(radius), _MIN_EXTENT_MM)

    height = max(2.0 * math.ceil(max_abs_z + pad), _MIN_EXTENT_MM)
    width_y = max(2.0 * math.ceil(max_abs_y + pad), _MIN_EXTENT_MM)
    if max_abs_y < _NEAR_ZERO_MM:
        width_y = height

    origin = StockOrigin(
        xy_corner=CORNER_LC,
        z_reference=Z_CENTER,
        offset_x_mm=min_x,
        offset_y_mm=0.0,
        offset_z_mm=0.0,
    )
    if kind == "rectangular":
        shape: StockShape = RectangularStock(width_mm=length, length_mm=width_y, height_mm=height)
    else:
        shape = RotaryCylindricalStock(diameter_mm=diameter, length_mm=length)
    return shape, origin


def shape_and_origin_from_cam_stock(cam_stock: CamStock) -> tuple[StockShape, StockOrigin]:
    """Convert parsed CAM header stock into the viewer's shape/origin types."""
    return shape_from_dict(cam_stock.to_shape_dict()), StockOrigin.from_dict(cam_stock.to_origin_dict())


def header_stock_usable(cam_stock: CamStock | None) -> bool:
    """True when a CAM-header stock can be converted into a viewer shape/origin."""
    if cam_stock is None:
        return False
    try:
        shape_and_origin_from_cam_stock(cam_stock)
        return True
    except (TypeError, ValueError, KeyError):
        return False


def auto_stock_for_loaded_file(
    cam_stock: CamStock | None,
    xmin: float,
    ymin: float,
    zmin: float,
    xmax: float,
    ymax: float,
    zmax: float,
    tool_table: dict | None = None,
    unit_scale: float = 1.0,
    feed_z_max_mm: float | None = None,
    rotary: bool = False,
    rotary_kind: str = RotaryCylindricalStock.kind,
) -> tuple[StockShape, StockOrigin]:
    """Prefer CAM-header stock; otherwise estimate from cutting bounds.

    Header stock is already in millimetres. ``unit_scale`` converts
    document-unit tool diameters when estimating from the toolpath.
    ``feed_z_max_mm`` is P95 of feed-move Z (same idea as the colour-scheme
    panel). For rotary files it must be raw WCS Z, not A-baked display Z.
    If the dimension of the stock can't be guessed fallback to the default values.
    """
    if header_stock_usable(cam_stock):
        return shape_and_origin_from_cam_stock(cam_stock)

    zmax_use = zmax
    if feed_z_max_mm is not None:
        zmax_use = min(zmax, float(feed_z_max_mm))

    pad_xy_mm = max_cutting_tool_diameter_mm(tool_table or {}, unit_scale) / 2.0
    if rotary:
        estimated = estimate_rotary_stock(xmin, ymin, zmin, xmax, ymax, zmax_use, pad_xy_mm, kind=rotary_kind)
        if estimated is not None:
            return estimated
        return default_rotary_shape(), default_rotary_origin()

    estimated = estimate_rectangular_stock(xmin, ymin, zmin, xmax, ymax, zmax_use, pad_xy_mm)
    if estimated is not None:
        return estimated
    return default_shape(), default_origin()
