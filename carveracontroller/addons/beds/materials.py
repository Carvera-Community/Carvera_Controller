"""Display-only bed material presets (addon-local, no stock imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MATERIAL_MDF = "mdf"
MATERIAL_ALUMINUM = "aluminum"

DEFAULT_MATERIAL = MATERIAL_MDF

KNOWN_MATERIALS = (MATERIAL_MDF, MATERIAL_ALUMINUM)

Rgb = tuple[float, float, float]


@dataclass(frozen=True)
class BedMaterialStyle:
    """Albedo and BRDF for one bed material id."""

    material_id: str
    albedo_rgb: Rgb
    metallic: float
    roughness: float


def normalize_bed_material(value: Any) -> str:
    """Return a known bed material id, defaulting to MDF."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in KNOWN_MATERIALS:
            return key
    return DEFAULT_MATERIAL


_STYLES: dict[str, BedMaterialStyle] = {
    MATERIAL_MDF: BedMaterialStyle(
        material_id=MATERIAL_MDF,
        albedo_rgb=(0.72, 0.58, 0.38),
        metallic=0.0,
        roughness=0.85,
    ),
    MATERIAL_ALUMINUM: BedMaterialStyle(
        material_id=MATERIAL_ALUMINUM,
        albedo_rgb=(0.68, 0.70, 0.72),
        metallic=1.0,
        roughness=0.48,
    ),
}


def style_for_bed_material(value: Any) -> BedMaterialStyle:
    """Style record for *value*, falling back to MDF."""
    return _STYLES[normalize_bed_material(value)]
