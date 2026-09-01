"""Place a stock shape into WCS using a StockOrigin."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .stock_origin import StockOrigin, named_origin_relative_to_center
from .stock_shape import StockShape


@dataclass(frozen=True)
class StockBounds:
    """Axis-aligned stock AABB in work coordinates (mm)."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def size(self) -> tuple[float, float, float]:
        return (
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            0.5 * (self.min_x + self.max_x),
            0.5 * (self.min_y + self.max_y),
            0.5 * (self.min_z + self.max_z),
        )


def rotate_yz(y: float, z: float, angle_deg: float) -> tuple[float, float]:
    """Rotate ``(y, z)`` around X by *angle_deg* (right-hand, degrees).

    Matches the G-code viewer's ``rotate_pt_by_x_axis_angle`` YZ mapping.
    """
    rad = math.radians(float(angle_deg))
    c = math.cos(rad)
    s = math.sin(rad)
    return (y * c - z * s, y * s + z * c)


def rotate_yz_np(y: np.ndarray, z: np.ndarray, angle_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized :func:`rotate_yz`."""
    rad = np.deg2rad(float(angle_deg))
    c = np.cos(rad)
    s = np.sin(rad)
    return y * c - z * s, y * s + z * c


def stock_theta_deg(
    y: float,
    z: float,
    angle_deg: float,
    axis_y: float = 0.0,
    axis_z: float = 0.0,
) -> float:
    """Stock-frame azimuth (degrees) of a machine YZ point at A-axis ``angle_deg``.

    Same convention as cylindrical mill occupancy: θ = atan2(Y, Z) − A about
    the axis after ``Rx(-A)``. Laser unwrap and the carved-stock shader use
    this θ, not raw A.
    """
    y_axis, z_axis = rotate_yz(float(axis_y), float(axis_z), -float(angle_deg))
    return math.degrees(math.atan2(float(y) - y_axis, float(z) - z_axis)) - float(angle_deg)


def compute_wcs_bounds(shape: StockShape, origin: StockOrigin) -> StockBounds:
    """Map a local stock shape into WCS using the given origin placement."""
    (_min_local, (dx, dy, dz)) = shape.local_bounds()
    ox_rel, oy_rel, oz_rel = named_origin_relative_to_center(dx, dy, dz, origin.xy_corner, origin.z_reference)
    # Named point sits at WCS origin; offsets then translate the whole AABB.
    cx = -ox_rel + origin.offset_x_mm
    cy = -oy_rel + origin.offset_y_mm
    cz = -oz_rel + origin.offset_z_mm
    half_x = 0.5 * dx
    half_y = 0.5 * dy
    half_z = 0.5 * dz
    return StockBounds(
        min_x=cx - half_x,
        min_y=cy - half_y,
        min_z=cz - half_z,
        max_x=cx + half_x,
        max_y=cy + half_y,
        max_z=cz + half_z,
    )


def wcs_to_local(bounds: StockBounds, x: float, y: float, z: float) -> tuple[float, float, float]:
    """Map a WCS point into the shape's local frame (min corner at origin)."""
    return (x - bounds.min_x, y - bounds.min_y, z - bounds.min_z)


def contains_wcs(shape: StockShape, bounds: StockBounds, x: float, y: float, z: float) -> bool:
    """True if the WCS point lies inside the placed solid (not just the AABB)."""
    lx, ly, lz = wcs_to_local(bounds, x, y, z)
    return shape.contains_local(lx, ly, lz)
