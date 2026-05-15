"""Machine coordinates (MCS) to active work XYZ via CNC.vars offsets."""

from __future__ import annotations

import math

from carveracontroller.CNC import CNC


def mcs_xyz_to_wcs_xyz(mx: float, my: float, mz: float) -> tuple[float, float, float]:
    """Map a machine-space XYZ point into active work XYZ (same frame as offsets)."""
    theta = math.radians(float(CNC.vars.get("rotation_angle", 0.0)))
    wcox = float(CNC.vars.get("wcox", 0.0))
    wcoy = float(CNC.vars.get("wcoy", 0.0))
    wcoz = float(CNC.vars.get("wcoz", 0.0))
    dx = mx - wcox
    dy = my - wcoy
    c = math.cos(theta)
    s = math.sin(theta)
    wx = c * dx + s * dy
    wy = -s * dx + c * dy
    wz = mz - wcoz
    return wx, wy, wz
