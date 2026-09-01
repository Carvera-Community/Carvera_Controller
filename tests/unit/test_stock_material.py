"""Stock material presets for preview and carved-mesh coloring."""

from carveracontroller.addons.stock.simulator.mesh_format import DEFAULT_COLOR
from carveracontroller.addons.stock.stock_aabb_mesh import STOCK_EDGE_COLOR, STOCK_FILL_COLOR
from carveracontroller.addons.stock.stock_defaults import default_settings, material_from_settings
from carveracontroller.addons.stock.stock_material import (
    DEFAULT_MATERIAL,
    MATERIAL_ACRYLIC,
    MATERIAL_ACRYLIC_BICOLOR,
    MATERIAL_ALUMINUM,
    MATERIAL_BEIGE,
    MATERIAL_COPPER,
    MATERIAL_PCB,
    normalize_stock_material,
    preview_fill_rgba,
    style_for_material,
)


def test_normalize_stock_material_fallbacks():
    assert normalize_stock_material("BEIGE") == MATERIAL_BEIGE
    assert normalize_stock_material("pcb") == MATERIAL_PCB
    assert normalize_stock_material("acrylic") == MATERIAL_ACRYLIC
    assert normalize_stock_material(None) == DEFAULT_MATERIAL
    assert normalize_stock_material("nope") == DEFAULT_MATERIAL
    assert normalize_stock_material("pcb_green") == DEFAULT_MATERIAL
    assert normalize_stock_material(12) == DEFAULT_MATERIAL


def test_default_settings_include_beige_material():
    settings = default_settings()
    assert settings["material"] == DEFAULT_MATERIAL
    assert material_from_settings(settings) == MATERIAL_BEIGE
    assert material_from_settings({}) == MATERIAL_BEIGE
    assert material_from_settings({"material": "PCB"}) == MATERIAL_PCB


def test_beige_keeps_current_preview_and_height_tint():
    style = style_for_material(MATERIAL_BEIGE)
    assert style.two_tone is False
    assert style.use_height_tint is True
    assert style.surface_rgb == DEFAULT_COLOR[:3]
    assert style.interior_rgb is None
    assert style.metallic == 0.0
    assert style.interior_metallic is None
    assert style.roughness == 0.92
    assert style.interior_roughness is None
    assert style.resolved_interior_rgb() == style.surface_rgb
    assert style.resolved_interior_metallic() == style.metallic
    assert style.resolved_interior_roughness() == style.roughness
    top, other, edge = preview_fill_rgba(style)
    assert top == STOCK_FILL_COLOR
    assert other == STOCK_FILL_COLOR
    assert edge == STOCK_EDGE_COLOR


def test_pcb_is_copper_over_fr4():
    style = style_for_material(MATERIAL_PCB)
    assert style.two_tone is True
    assert style.use_height_tint is False
    assert style.surface_rgb == (0.85, 0.55, 0.22)
    assert style.metallic == 1.0
    assert style.interior_metallic == 0.0
    assert style.roughness == 0.45
    assert style.interior_roughness == 0.85
    top, other, edge = preview_fill_rgba(style)
    assert top[:3] == style.surface_rgb
    assert other[:3] == style.interior_rgb
    assert other[:3] != top[:3]
    assert edge[3] == style.edge_rgba[3]
    assert style.surface_thickness_mm < 0.05


def test_aluminum_is_uniform_metal():
    style = style_for_material(MATERIAL_ALUMINUM)
    assert style.two_tone is False
    assert style.metallic == 1.0
    assert style.interior_rgb is None
    assert style.interior_metallic is None
    assert style.interior_roughness is None
    assert style.resolved_interior_metallic() == 1.0
    assert style.resolved_interior_roughness() == style.roughness


def test_copper_is_uniform_metal():
    style = style_for_material(MATERIAL_COPPER)
    assert style.two_tone is False
    assert style.use_height_tint is False
    assert style.metallic == 1.0
    assert style.interior_metallic is None
    assert style.interior_roughness is None
    assert style.resolved_interior_metallic() == 1.0
    top, other, _edge = preview_fill_rgba(style)
    assert top[:3] == style.surface_rgb
    assert other[:3] == style.surface_rgb


def test_only_layered_materials_use_a_second_albedo():
    from carveracontroller.addons.stock.stock_material import KNOWN_MATERIALS

    layered = {MATERIAL_PCB, MATERIAL_ACRYLIC_BICOLOR}
    for material_id in KNOWN_MATERIALS:
        style = style_for_material(material_id)
        if material_id in layered:
            assert style.interior_rgb is not None
            assert style.interior_rgb != style.surface_rgb
            assert style.two_tone is True
        else:
            assert style.interior_rgb is None
            assert style.two_tone is False


def test_acrylic_bicolor_is_white_over_black():
    style = style_for_material(MATERIAL_ACRYLIC_BICOLOR)
    assert style.two_tone is True
    assert style.metallic == 0.0
    assert style.interior_metallic is None
    assert style.surface_rgb[0] > 0.9
    assert style.interior_rgb[0] < 0.15
    top, other, _edge = preview_fill_rgba(style)
    assert top[:3] == style.surface_rgb
    assert other[:3] == style.interior_rgb
