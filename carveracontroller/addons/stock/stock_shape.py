"""Abstract and concrete stock shapes (workpiece volumes)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar


class StockShape(ABC):
    """Base class for a workpiece volume in local (unplaced) coordinates.

    Local bounds always start at the origin corner (0, 0, 0) and extend
    positively along each axis.
    """

    kind: ClassVar[str]

    @abstractmethod
    def local_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return ``((0, 0, 0), (dx, dy, dz))`` in millimetres."""

    @abstractmethod
    def contains_local(self, x: float, y: float, z: float) -> bool:
        """True if the point lies inside the solid in local millimetres."""

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict (includes ``kind``)."""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> StockShape:
        """Deserialize from a dict produced by :meth:`to_dict`."""


@dataclass(frozen=True)
class RectangularStock(StockShape):
    """Axis-aligned rectangular block stock.

    Dimensions are in millimetres:
    - ``width_mm``  -> X extent
    - ``length_mm`` -> Y extent
    - ``height_mm`` -> Z extent
    """

    kind: ClassVar[str] = "rectangular"

    width_mm: float
    length_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        if self.width_mm <= 0 or self.length_mm <= 0 or self.height_mm <= 0:
            raise ValueError("RectangularStock dimensions must be positive")

    def local_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return (0.0, 0.0, 0.0), (self.width_mm, self.length_mm, self.height_mm)

    def contains_local(self, x: float, y: float, z: float) -> bool:
        return 0.0 <= x <= self.width_mm and 0.0 <= y <= self.length_mm and 0.0 <= z <= self.height_mm

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "width_mm": float(self.width_mm),
            "length_mm": float(self.length_mm),
            "height_mm": float(self.height_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RectangularStock:
        return cls(
            width_mm=float(data["width_mm"]),
            length_mm=float(data["length_mm"]),
            height_mm=float(data["height_mm"]),
        )


@dataclass(frozen=True)
class CylindricalStock(StockShape):
    """Z-axis cylindrical stock (round billet standing on end).

    Dimensions are in millimetres:
    - ``diameter_mm`` -> X and Y extent of the bounding square
    - ``height_mm``   -> Z extent
    """

    kind: ClassVar[str] = "cylindrical"

    diameter_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        if self.diameter_mm <= 0 or self.height_mm <= 0:
            raise ValueError("CylindricalStock dimensions must be positive")

    def local_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        d = self.diameter_mm
        return (0.0, 0.0, 0.0), (d, d, self.height_mm)

    def contains_local(self, x: float, y: float, z: float) -> bool:
        if not (0.0 <= z <= self.height_mm):
            return False
        r = 0.5 * self.diameter_mm
        dx = x - r
        dy = y - r
        return (dx * dx + dy * dy) <= (r * r)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "diameter_mm": float(self.diameter_mm),
            "height_mm": float(self.height_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CylindricalStock:
        return cls(
            diameter_mm=float(data["diameter_mm"]),
            height_mm=float(data["height_mm"]),
        )


@dataclass(frozen=True)
class RotaryCylindricalStock(StockShape):
    """X-axis cylindrical bar (round stock in a 4th-axis rotary).

    Dimensions are in millimetres:
    - ``length_mm``    -> X extent (along the A / rotation axis)
    - ``diameter_mm``  -> Y and Z extent of the bounding square
    """

    kind: ClassVar[str] = "rotary_cylindrical"

    diameter_mm: float
    length_mm: float

    def __post_init__(self) -> None:
        if self.diameter_mm <= 0 or self.length_mm <= 0:
            raise ValueError("RotaryCylindricalStock dimensions must be positive")

    def local_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        d = self.diameter_mm
        return (0.0, 0.0, 0.0), (self.length_mm, d, d)

    def contains_local(self, x: float, y: float, z: float) -> bool:
        if not (0.0 <= x <= self.length_mm):
            return False
        r = 0.5 * self.diameter_mm
        dy = y - r
        dz = z - r
        return (dy * dy + dz * dz) <= (r * r)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "diameter_mm": float(self.diameter_mm),
            "length_mm": float(self.length_mm),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RotaryCylindricalStock:
        return cls(
            diameter_mm=float(data["diameter_mm"]),
            length_mm=float(data["length_mm"]),
        )


_SHAPE_REGISTRY: dict[str, type[StockShape]] = {
    RectangularStock.kind: RectangularStock,
    CylindricalStock.kind: CylindricalStock,
    RotaryCylindricalStock.kind: RotaryCylindricalStock,
}


def shape_from_dict(data: dict[str, Any]) -> StockShape:
    """Deserialize any registered stock shape from a dict."""
    if not isinstance(data, dict):
        raise ValueError("stock shape data must be a dict")
    kind = data.get("kind")
    cls = _SHAPE_REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"unknown stock shape kind: {kind!r}")
    return cls.from_dict(data)
