"""CAM-header metadata extracted from G-code comments."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition


@dataclass(frozen=True)
class CamStock:
    """Stock definition in millimetres, parsed from a CAM post-processor header."""

    kind: str
    width_mm: float | None = None
    length_mm: float | None = None
    height_mm: float | None = None
    diameter_mm: float | None = None
    xy_corner: str = "bl"
    z_reference: str = "top"
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    offset_z_mm: float = 0.0

    def to_shape_dict(self) -> dict:
        if self.kind == "rotary_cylindrical":
            return {
                "kind": "rotary_cylindrical",
                "diameter_mm": float(self.diameter_mm),
                "length_mm": float(self.length_mm),
            }
        if self.kind == "cylindrical":
            return {
                "kind": "cylindrical",
                "diameter_mm": float(self.diameter_mm),
                "height_mm": float(self.height_mm),
            }
        return {
            "kind": "rectangular",
            "width_mm": float(self.width_mm),
            "length_mm": float(self.length_mm),
            "height_mm": float(self.height_mm),
        }

    def to_origin_dict(self) -> dict:
        return {
            "xy_corner": self.xy_corner,
            "z_reference": self.z_reference,
            "offset_x_mm": float(self.offset_x_mm),
            "offset_y_mm": float(self.offset_y_mm),
            "offset_z_mm": float(self.offset_z_mm),
        }

    def scaled(self, factor: float) -> CamStock:
        """Return a copy with sizes and offsets multiplied by ``factor``.

        Posts emit stock in document units. Call this with ``unit_scale_to_mm``
        before keeping the object so fields are in millimetres.
        """
        scale = float(factor) if factor else 1.0
        if scale == 1.0:
            return self

        def _scale(value: float | None) -> float | None:
            return None if value is None else value * scale

        return replace(
            self,
            width_mm=_scale(self.width_mm),
            length_mm=_scale(self.length_mm),
            height_mm=_scale(self.height_mm),
            diameter_mm=_scale(self.diameter_mm),
            offset_x_mm=self.offset_x_mm * scale,
            offset_y_mm=self.offset_y_mm * scale,
            offset_z_mm=self.offset_z_mm * scale,
        )


@dataclass(frozen=True)
class CamMetadata:
    """Result of scanning a G-code file for CAM header comments."""

    parser_name: str | None
    tool_table: dict[int, ToolDefinition] = field(default_factory=dict)
    stock: CamStock | None = None

    @classmethod
    def empty(cls) -> CamMetadata:
        return cls(parser_name=None, tool_table={}, stock=None)
