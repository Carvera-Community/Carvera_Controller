"""In-memory stock defaults (no disk persistence)."""

from __future__ import annotations

from typing import Any

from .simulator.carver_select import DEFAULT_CARVER_MODE, normalize_carver_mode
from .simulator.simulation_quality import (
    DEFAULT_CHECKPOINT_LEVEL,
    DEFAULT_VOXEL_RESOLUTION,
    normalize_checkpoint_level,
    normalize_voxel_resolution,
)
from .stock_geometry import StockBounds, compute_wcs_bounds
from .stock_material import DEFAULT_MATERIAL, normalize_stock_material
from .stock_origin import CORNER_BL, CORNER_LC, Z_CENTER, Z_TOP, StockOrigin
from .stock_shape import RectangularStock, RotaryCylindricalStock, StockShape, shape_from_dict

DEFAULT_WIDTH_MM = 100.0
DEFAULT_LENGTH_MM = 100.0
DEFAULT_HEIGHT_MM = 10.0
DEFAULT_DIAMETER_MM = 100.0


def default_shape() -> RectangularStock:
    return RectangularStock(
        width_mm=DEFAULT_WIDTH_MM,
        length_mm=DEFAULT_LENGTH_MM,
        height_mm=DEFAULT_HEIGHT_MM,
    )


def default_origin() -> StockOrigin:
    return StockOrigin(xy_corner=CORNER_BL, z_reference=Z_TOP)


def default_rotary_shape() -> RotaryCylindricalStock:
    return RotaryCylindricalStock(diameter_mm=DEFAULT_DIAMETER_MM, length_mm=DEFAULT_WIDTH_MM)


def default_rotary_origin() -> StockOrigin:
    return StockOrigin(xy_corner=CORNER_LC, z_reference=Z_CENTER)


def default_bounds() -> StockBounds:
    return compute_wcs_bounds(default_shape(), default_origin())


def default_settings() -> dict[str, Any]:
    return {
        "shape": default_shape().to_dict(),
        "origin": default_origin().to_dict(),
        "show_stock": False,
        "simulate_cut": False,
        "mesh_while_playing": False,
        "voxel_resolution": DEFAULT_VOXEL_RESOLUTION,
        "checkpoint_level": DEFAULT_CHECKPOINT_LEVEL,
        "carver_mode": DEFAULT_CARVER_MODE,
        "material": DEFAULT_MATERIAL,
    }


def shape_from_settings(settings: dict[str, Any]) -> StockShape:
    return shape_from_dict(settings["shape"])


def origin_from_settings(settings: dict[str, Any]) -> StockOrigin:
    return StockOrigin.from_dict(settings["origin"])


def bounds_from_settings(settings: dict[str, Any]) -> StockBounds:
    return compute_wcs_bounds(shape_from_settings(settings), origin_from_settings(settings))


def voxel_resolution_from_settings(settings: dict[str, Any]) -> str:
    return normalize_voxel_resolution(settings.get("voxel_resolution"))


def checkpoint_level_from_settings(settings: dict[str, Any]) -> str:
    return normalize_checkpoint_level(settings.get("checkpoint_level"))


def mesh_while_playing_from_settings(settings: dict[str, Any]) -> bool:
    return bool(settings.get("mesh_while_playing", False))


def carver_mode_from_settings(settings: dict[str, Any]) -> str:
    return normalize_carver_mode(settings.get("carver_mode"))


def material_from_settings(settings: dict[str, Any]) -> str:
    return normalize_stock_material(settings.get("material"))
