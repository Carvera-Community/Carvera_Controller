"""Unit tests for stock simulation quality presets."""

import math

import pytest

from carveracontroller.addons.stock.simulator import CheckpointStore
from carveracontroller.addons.stock.simulator.simulation_quality import (
    CHECKPOINT_SLOTS_BY_LEVEL,
    CYLINDRICAL_TARGET_BY_LEVEL,
    DEFAULT_CHECKPOINT_LEVEL,
    DEFAULT_VOXEL_RESOLUTION,
    HEIGHTMAP_TARGET_BY_LEVEL,
    MIN_CELL_SIZE_MM,
    VOXEL_TARGET_BY_LEVEL,
    cell_target_for_carver,
    checkpoint_slots_for_level,
    format_cell_size_mm,
    format_diameter_mm,
    normalize_checkpoint_level,
    normalize_voxel_resolution,
    pick_cell_size_mm,
)
from carveracontroller.addons.stock.stock_defaults import (
    checkpoint_level_from_settings,
    default_settings,
    mesh_while_playing_from_settings,
    voxel_resolution_from_settings,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds


def test_voxel_preset_defaults():
    assert VOXEL_TARGET_BY_LEVEL["low"] == 100
    assert HEIGHTMAP_TARGET_BY_LEVEL["high"] == 1000
    assert HEIGHTMAP_TARGET_BY_LEVEL["high"] > VOXEL_TARGET_BY_LEVEL["high"]
    assert DEFAULT_VOXEL_RESOLUTION == "low"


def test_cell_target_for_carver():
    assert cell_target_for_carver("voxel", "high") == VOXEL_TARGET_BY_LEVEL["high"]
    assert cell_target_for_carver("heightmap", "high") == HEIGHTMAP_TARGET_BY_LEVEL["high"]
    assert cell_target_for_carver("cylindrical", "medium") == 400
    assert cell_target_for_carver("unknown", "low") == VOXEL_TARGET_BY_LEVEL["low"]


def test_checkpoint_slots_match_presets_and_store_default():
    assert CHECKPOINT_SLOTS_BY_LEVEL == {"low": 256, "medium": 1024, "high": 4096}
    store = CheckpointStore()
    assert store.slot_count == CHECKPOINT_SLOTS_BY_LEVEL["medium"]
    assert store.base_interval == 4
    assert checkpoint_slots_for_level("high") == 4096
    assert checkpoint_slots_for_level("bogus") == CHECKPOINT_SLOTS_BY_LEVEL[DEFAULT_CHECKPOINT_LEVEL]
    assert DEFAULT_CHECKPOINT_LEVEL == "medium"


def test_normalize_voxel_resolution_fallbacks():
    assert normalize_voxel_resolution("HIGH") == "high"
    assert normalize_voxel_resolution("medium") == "medium"
    assert normalize_voxel_resolution(None) == DEFAULT_VOXEL_RESOLUTION
    assert normalize_voxel_resolution("nope") == DEFAULT_VOXEL_RESOLUTION
    assert normalize_voxel_resolution(12) == DEFAULT_VOXEL_RESOLUTION


def test_normalize_checkpoint_level_fallbacks():
    assert normalize_checkpoint_level("LOW") == "low"
    assert normalize_checkpoint_level("high") == "high"
    assert normalize_checkpoint_level(None) == DEFAULT_CHECKPOINT_LEVEL
    assert normalize_checkpoint_level("") == DEFAULT_CHECKPOINT_LEVEL
    assert normalize_checkpoint_level({}) == DEFAULT_CHECKPOINT_LEVEL


def test_pick_cell_size_heightmap_levels_differ_on_small_stock():
    """2D carvers must not inherit the 0.1 mm voxel floor (42 mm PCB case)."""
    bounds = StockBounds(0, 0, 0, 42, 42, 1)
    low = pick_cell_size_mm(bounds, carver="heightmap", level="low")
    mid = pick_cell_size_mm(bounds, carver="heightmap", level="medium")
    high = pick_cell_size_mm(bounds, carver="heightmap", level="high")
    assert low == pytest.approx(42 / HEIGHTMAP_TARGET_BY_LEVEL["low"])
    assert mid == pytest.approx(42 / HEIGHTMAP_TARGET_BY_LEVEL["medium"])
    assert high == pytest.approx(MIN_CELL_SIZE_MM["heightmap"])
    assert high < mid < low
    assert high < MIN_CELL_SIZE_MM["voxel"]


def test_pick_cell_size_heightmap_uses_xy_not_z():
    bounds = StockBounds(0, 0, 0, 100, 20, 50)
    high = pick_cell_size_mm(bounds, carver="heightmap", level="high")
    assert high == pytest.approx(100 / HEIGHTMAP_TARGET_BY_LEVEL["high"])


def test_pick_cell_size_cylindrical_uses_x_length():
    bounds = StockBounds(0, 0, 0, 200, 20, 20)
    high = pick_cell_size_mm(bounds, carver="cylindrical", level="high")
    assert high == pytest.approx(200 / CYLINDRICAL_TARGET_BY_LEVEL["high"])


def test_pick_cell_size_cylindrical_uses_circumference_on_short_puck():
    """A short fat rotary puck must not use X-only cell size (θ would explode)."""
    bounds = StockBounds(0, -40, -40, 5, 40, 40)
    high = pick_cell_size_mm(bounds, carver="cylindrical", level="high")
    circumference = math.pi * 80.0
    target = CYLINDRICAL_TARGET_BY_LEVEL["high"]
    assert high == pytest.approx(circumference / target)
    assert high > 5 / target


def test_pick_cell_size_cylindrical_long_bar_stays_fine_along_x():
    """A long thin bar at High still targets ~800 cells along X."""
    bounds = StockBounds(0, -15, -15, 200, 15, 15)
    high = pick_cell_size_mm(bounds, carver="cylindrical", level="high")
    assert high == pytest.approx(200 / CYLINDRICAL_TARGET_BY_LEVEL["high"])


def test_pick_cell_size_voxel_still_clamps_small_stock():
    bounds = StockBounds(0, 0, 0, 20, 20, 5)
    high = pick_cell_size_mm(bounds, carver="voxel", level="high")
    assert high == pytest.approx(MIN_CELL_SIZE_MM["voxel"])


def test_format_cell_size_mm():
    assert format_cell_size_mm(0.21) == "0.21"
    assert format_cell_size_mm(0.10) == "0.10"
    assert format_cell_size_mm(0.042) == "0.042"
    assert format_cell_size_mm(1.0) == "1.0"
    assert format_cell_size_mm(12.0) == "12"


def test_format_diameter_mm():
    assert format_diameter_mm(50.0) == "50"
    assert format_diameter_mm(28.0) == "28"
    assert format_diameter_mm(12.7) == "12.7"
    assert format_diameter_mm(12.74) == "12.7"


def test_default_settings_include_quality_presets():
    settings = default_settings()
    assert settings["voxel_resolution"] == DEFAULT_VOXEL_RESOLUTION
    assert settings["checkpoint_level"] == DEFAULT_CHECKPOINT_LEVEL
    assert settings["mesh_while_playing"] is False
    assert settings["material"] == "beige"
    assert voxel_resolution_from_settings(settings) == DEFAULT_VOXEL_RESOLUTION
    assert checkpoint_level_from_settings(settings) == DEFAULT_CHECKPOINT_LEVEL
    assert mesh_while_playing_from_settings(settings) is False


def test_settings_helpers_normalize_bad_values():
    assert voxel_resolution_from_settings({}) == DEFAULT_VOXEL_RESOLUTION
    assert checkpoint_level_from_settings({"checkpoint_level": "bogus"}) == DEFAULT_CHECKPOINT_LEVEL
    assert voxel_resolution_from_settings({"voxel_resolution": "High"}) == "high"
    assert mesh_while_playing_from_settings({}) is False
    assert mesh_while_playing_from_settings({"mesh_while_playing": False}) is False
    assert mesh_while_playing_from_settings({"mesh_while_playing": 0}) is False
    assert mesh_while_playing_from_settings({"mesh_while_playing": True}) is True
