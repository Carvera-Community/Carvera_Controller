"""Where the WCS origin sits relative to the stock."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Front = Y min, Back = Y max (Fusion / Makera), independent of Z.
CORNER_BL = "bl"  # Front-left
CORNER_BR = "br"  # Front-right
CORNER_TL = "tl"  # Back-left
CORNER_TR = "tr"  # Back-right
CORNER_CENTER = "center"
CORNER_LC = "lc"  # Center-left
CORNER_RC = "rc"  # Center-right
CORNER_FC = "fc"  # Front-center
CORNER_BC = "bc"  # Back-center

Z_TOP = "top"
Z_BOTTOM = "bottom"
Z_CENTER = "center"

XY_CORNERS = frozenset(
    {
        CORNER_BL,
        CORNER_BR,
        CORNER_TL,
        CORNER_TR,
        CORNER_CENTER,
        CORNER_LC,
        CORNER_RC,
        CORNER_FC,
        CORNER_BC,
    }
)
Z_REFERENCES = frozenset({Z_TOP, Z_BOTTOM, Z_CENTER})


def _finite_offset(value: Any, name: str) -> float:
    try:
        offset = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number, got {value!r}") from exc
    if not math.isfinite(offset):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return offset


def named_origin_relative_to_center(dx, dy, dz, xy_corner, z_reference):
    """WCS origin relative to the stock AABB centre for a named XY point and Z.

    X, Y, and Z are independent: ``z_reference=center`` only zeroes Z.
    """
    half_x = dx / 2.0
    half_y = dy / 2.0
    half_z = dz / 2.0
    corner = (xy_corner or "").strip().lower()
    z_ref = (z_reference or "").strip().lower()

    xy_from_center = {
        CORNER_BL: (-half_x, -half_y),
        CORNER_BR: (half_x, -half_y),
        CORNER_TL: (-half_x, half_y),
        CORNER_TR: (half_x, half_y),
        CORNER_FC: (0.0, -half_y),
        CORNER_BC: (0.0, half_y),
        CORNER_LC: (-half_x, 0.0),
        CORNER_RC: (half_x, 0.0),
        CORNER_CENTER: (0.0, 0.0),
    }
    if corner not in xy_from_center:
        raise ValueError(f"xy_corner must be one of {sorted(XY_CORNERS)}, got {xy_corner!r}")
    x, y = xy_from_center[corner]

    if z_ref == Z_CENTER:
        z = 0.0
    elif z_ref == Z_BOTTOM:
        z = -half_z
    elif z_ref == Z_TOP:
        z = half_z
    else:
        raise ValueError(f"z_reference must be one of {sorted(Z_REFERENCES)}, got {z_reference!r}")
    return x, y, z


@dataclass(frozen=True)
class StockOrigin:
    """Placement of the stock AABB in WCS; offsets translate the stock block."""

    xy_corner: str = CORNER_BL
    z_reference: str = Z_TOP
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    offset_z_mm: float = 0.0

    def __post_init__(self) -> None:
        corner = self.xy_corner.strip().lower()
        z_ref = self.z_reference.strip().lower()
        if corner not in XY_CORNERS:
            raise ValueError(f"xy_corner must be one of {sorted(XY_CORNERS)}, got {self.xy_corner!r}")
        if z_ref not in Z_REFERENCES:
            raise ValueError(f"z_reference must be one of {sorted(Z_REFERENCES)}, got {self.z_reference!r}")
        object.__setattr__(self, "xy_corner", corner)
        object.__setattr__(self, "z_reference", z_ref)
        object.__setattr__(self, "offset_x_mm", _finite_offset(self.offset_x_mm, "offset_x_mm"))
        object.__setattr__(self, "offset_y_mm", _finite_offset(self.offset_y_mm, "offset_y_mm"))
        object.__setattr__(self, "offset_z_mm", _finite_offset(self.offset_z_mm, "offset_z_mm"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "xy_corner": self.xy_corner,
            "z_reference": self.z_reference,
            "offset_x_mm": self.offset_x_mm,
            "offset_y_mm": self.offset_y_mm,
            "offset_z_mm": self.offset_z_mm,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StockOrigin:
        if not data:
            return cls()
        return cls(
            xy_corner=str(data.get("xy_corner", CORNER_BL)),
            z_reference=str(data.get("z_reference", Z_TOP)),
            offset_x_mm=data.get("offset_x_mm", 0.0),
            offset_y_mm=data.get("offset_y_mm", 0.0),
            offset_z_mm=data.get("offset_z_mm", 0.0),
        )
