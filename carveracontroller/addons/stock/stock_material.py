"""Display-only stock material presets (preview fill + carved-mesh shader)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .simulator.mesh_format import DEFAULT_COLOR
from .stock_aabb_mesh import STOCK_EDGE_COLOR, STOCK_FILL_COLOR

MATERIAL_BEIGE = "beige"
MATERIAL_PCB = "pcb"
MATERIAL_WOOD = "wood"
MATERIAL_ACRYLIC = "acrylic"
MATERIAL_ACRYLIC_BICOLOR = "acrylic_bicolor"
MATERIAL_ALUMINUM = "aluminum"
MATERIAL_COPPER = "copper"

DEFAULT_MATERIAL = MATERIAL_BEIGE

KNOWN_MATERIALS = (
    MATERIAL_BEIGE,
    MATERIAL_PCB,
    MATERIAL_WOOD,
    MATERIAL_ACRYLIC,
    MATERIAL_ACRYLIC_BICOLOR,
    MATERIAL_ALUMINUM,
    MATERIAL_COPPER,
)

Rgb = tuple[float, float, float]
Rgba = tuple[float, float, float, float]


@dataclass(frozen=True)
class StockMaterialStyle:
    """GPU/preview colors and carved-mesh BRDF for one stock material id."""

    material_id: str
    surface_rgb: Rgb
    fill_alpha: float
    edge_rgba: Rgba
    use_height_tint: bool
    preview_rgb: Rgb | None = None
    interior_rgb: Rgb | None = None
    surface_thickness_mm: float = 0.1
    metallic: float = 0.0
    interior_metallic: float | None = None
    roughness: float = 0.92
    interior_roughness: float | None = None

    @property
    def two_tone(self) -> bool:
        """True when cuts reveal a second albedo (PCB foil, bicolor core)."""
        return self.interior_rgb is not None

    def resolved_interior_rgb(self) -> Rgb:
        return self.surface_rgb if self.interior_rgb is None else self.interior_rgb

    def resolved_interior_metallic(self) -> float:
        return self.metallic if self.interior_metallic is None else self.interior_metallic

    def resolved_interior_roughness(self) -> float:
        return self.roughness if self.interior_roughness is None else self.interior_roughness


def normalize_stock_material(value: Any) -> str:
    """Return a known material id, defaulting to Default (beige)."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in KNOWN_MATERIALS:
            return key
    return DEFAULT_MATERIAL


_STYLES: dict[str, StockMaterialStyle] = {
    MATERIAL_BEIGE: StockMaterialStyle(
        material_id=MATERIAL_BEIGE,
        surface_rgb=(DEFAULT_COLOR[0], DEFAULT_COLOR[1], DEFAULT_COLOR[2]),
        fill_alpha=STOCK_FILL_COLOR[3],
        edge_rgba=STOCK_EDGE_COLOR,
        use_height_tint=True,
        preview_rgb=(STOCK_FILL_COLOR[0], STOCK_FILL_COLOR[1], STOCK_FILL_COLOR[2]),
        surface_thickness_mm=0.0,
        roughness=0.92,
    ),
    MATERIAL_PCB: StockMaterialStyle(
        material_id=MATERIAL_PCB,
        surface_rgb=(0.85, 0.55, 0.22),
        fill_alpha=0.38,
        edge_rgba=(0.65, 0.40, 0.15, 0.90),
        use_height_tint=False,
        interior_rgb=(0.52, 0.48, 0.28),
        surface_thickness_mm=0.035,
        metallic=1.0,
        interior_metallic=0.0,
        roughness=0.45,
        interior_roughness=0.85,
    ),
    MATERIAL_WOOD: StockMaterialStyle(
        material_id=MATERIAL_WOOD,
        surface_rgb=(0.52, 0.34, 0.18),
        fill_alpha=0.36,
        edge_rgba=(0.62, 0.42, 0.22, 0.90),
        use_height_tint=False,
        roughness=0.80,
    ),
    MATERIAL_ACRYLIC: StockMaterialStyle(
        material_id=MATERIAL_ACRYLIC,
        surface_rgb=(0.62, 0.78, 0.86),
        fill_alpha=0.16,
        edge_rgba=(0.75, 0.88, 0.94, 0.70),
        use_height_tint=False,
        roughness=0.12,
    ),
    MATERIAL_ACRYLIC_BICOLOR: StockMaterialStyle(
        material_id=MATERIAL_ACRYLIC_BICOLOR,
        surface_rgb=(0.96, 0.96, 0.97),
        fill_alpha=0.22,
        edge_rgba=(0.88, 0.88, 0.90, 0.80),
        use_height_tint=False,
        interior_rgb=(0.05, 0.05, 0.06),
        surface_thickness_mm=0.05,
        roughness=0.12,
        interior_roughness=0.40,
    ),
    MATERIAL_ALUMINUM: StockMaterialStyle(
        material_id=MATERIAL_ALUMINUM,
        surface_rgb=(0.68, 0.70, 0.72),
        fill_alpha=0.32,
        edge_rgba=(0.88, 0.90, 0.92, 0.90),
        use_height_tint=False,
        metallic=1.0,
        roughness=0.48,
    ),
    MATERIAL_COPPER: StockMaterialStyle(
        material_id=MATERIAL_COPPER,
        surface_rgb=(0.72, 0.40, 0.16),
        fill_alpha=0.32,
        edge_rgba=(0.90, 0.55, 0.22, 0.90),
        use_height_tint=False,
        metallic=1.0,
        roughness=0.50,
    ),
}


def style_for_material(value: Any) -> StockMaterialStyle:
    """Style record for *value*, falling back to Default."""
    return _STYLES[normalize_stock_material(value)]


def preview_fill_rgba(style: StockMaterialStyle) -> tuple[Rgba, Rgba, Rgba]:
    """Return ``(top, other, edge)`` preview colors for the uncut stock shell."""
    alpha = float(style.fill_alpha)
    top_rgb = style.preview_rgb if style.preview_rgb is not None else style.surface_rgb
    other_rgb = style.interior_rgb if style.interior_rgb is not None else top_rgb
    top = (top_rgb[0], top_rgb[1], top_rgb[2], alpha)
    other = (other_rgb[0], other_rgb[1], other_rgb[2], alpha)
    return top, other, style.edge_rgba
