"""Bed material presets stay local to the addon."""

from pathlib import Path

import carveracontroller.addons.beds.materials as materials_mod
from carveracontroller.addons.beds.materials import (
    DEFAULT_MATERIAL,
    MATERIAL_ALUMINUM,
    MATERIAL_MDF,
    normalize_bed_material,
    style_for_bed_material,
)


def test_known_ids_and_defaults():
    assert normalize_bed_material("MDF") == MATERIAL_MDF
    assert normalize_bed_material("aluminum") == MATERIAL_ALUMINUM
    assert normalize_bed_material("nope") == DEFAULT_MATERIAL
    assert normalize_bed_material(None) == DEFAULT_MATERIAL
    assert DEFAULT_MATERIAL == MATERIAL_MDF


def test_mdf_is_matte_tan():
    style = style_for_bed_material(MATERIAL_MDF)
    assert style.metallic == 0.0
    assert abs(style.roughness - 0.85) < 1e-9
    assert style.albedo_rgb[0] > style.albedo_rgb[2]


def test_aluminum_is_metal():
    style = style_for_bed_material(MATERIAL_ALUMINUM)
    assert style.metallic == 1.0
    assert abs(style.roughness - 0.48) < 1e-9


def test_addon_does_not_import_stock():
    root = Path(materials_mod.__file__).resolve().parent
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "addons.stock" not in text
        assert "stock_material" not in text
