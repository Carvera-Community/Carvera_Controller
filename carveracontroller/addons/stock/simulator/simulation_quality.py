"""Preset tables for stock cut-simulation quality / memory trade-offs."""

from __future__ import annotations

import math
from typing import Any

from carveracontroller.addons.stock.stock_geometry import StockBounds

# Target cells along the carver's reference length (see ``_reference_length_mm``).
DEFAULT_VOXEL_RESOLUTION = "low"
RESOLUTION_LEVELS = ("low", "medium", "high")

# 3D voxels are memory-heavy — keep targets modest.
VOXEL_TARGET_BY_LEVEL = {
    "low": 100,
    "medium": 300,
    "high": 500,
}

# Heightmaps are 2D float arrays — can run denser for the same memory budget.
HEIGHTMAP_TARGET_BY_LEVEL = {
    "low": 200,
    "medium": 500,
    "high": 1000,
}

# Cylindrical r(x,θ) is 2D; cell size uses max(X, πD) so a short large-diameter
# puck does not explode in θ while a long bar stays fine-pitched along X.
CYLINDRICAL_TARGET_BY_LEVEL = {
    "low": 150,
    "medium": 400,
    "high": 800,
}

_TARGET_BY_CARVER = {
    "voxel": VOXEL_TARGET_BY_LEVEL,
    "heightmap": HEIGHTMAP_TARGET_BY_LEVEL,
    "cylindrical": CYLINDRICAL_TARGET_BY_LEVEL,
}

# Minimum cell size (mm).
MIN_CELL_SIZE_MM = {
    "voxel": 0.1,
    "heightmap": 0.05,
    "cylindrical": 0.2,
}
MAX_CELL_SIZE_MM = {
    "voxel": 1.0,
    "heightmap": 1.0,
    "cylindrical": 1.0,
}

# Equally spaced restore-point slots along the toolpath
DEFAULT_CHECKPOINT_LEVEL = "medium"
CHECKPOINT_SLOTS_BY_LEVEL = {
    "low": 256,
    "medium": 1024,
    "high": 4096,
}


def normalize_voxel_resolution(value: Any) -> str:
    """Return a known resolution level, defaulting to ``low``."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in VOXEL_TARGET_BY_LEVEL:
            return key
    return DEFAULT_VOXEL_RESOLUTION


def cell_target_for_carver(carver: str, level: Any) -> int:
    """Cells along the reference length for ``carver`` at resolution ``level``."""
    key = normalize_voxel_resolution(level)
    table = _TARGET_BY_CARVER.get(str(carver).strip().lower(), VOXEL_TARGET_BY_LEVEL)
    return int(table[key])


def _carver_key(carver: str) -> str:
    key = str(carver).strip().lower()
    return key if key in _TARGET_BY_CARVER else "voxel"


def _reference_length_mm(carver: str, bounds: StockBounds) -> float:
    """Length that the cell-count target is measured against."""
    sx, sy, sz = bounds.size
    kind = _carver_key(carver)
    if kind == "heightmap":
        return max(float(sx), float(sy), 1e-6)
    if kind == "cylindrical":
        diameter = min(float(sy), float(sz))
        circumference = math.pi * max(diameter, 0.0)
        return max(float(sx), circumference, 1e-6)
    return max(float(sx), float(sy), float(sz), 1e-6)


def pick_cell_size_mm(
    bounds: StockBounds,
    *,
    carver: str = "voxel",
    level: Any = None,
    target: int | None = None,
) -> float:
    """Cell/voxel edge so the reference length has roughly ``target`` samples."""
    kind = _carver_key(carver)
    n = int(target) if target is not None else cell_target_for_carver(kind, level)
    size = _reference_length_mm(kind, bounds) / max(n, 1)
    lo = float(MIN_CELL_SIZE_MM[kind])
    hi = float(MAX_CELL_SIZE_MM[kind])
    return float(min(hi, max(lo, size)))


def format_cell_size_mm(cell_mm: float) -> str:
    """Compact millimetre text for HUD / settings labels."""
    v = float(cell_mm)
    if v >= 10.0:
        return f"{v:.0f}"
    if v >= 1.0 or abs(v - round(v)) < 1e-6:
        return f"{v:.1f}"
    if v >= 0.095:
        return f"{v:.2f}"
    text = f"{v:.3f}".rstrip("0").rstrip(".")
    return text if text else "0"


def format_diameter_mm(diameter_mm: float) -> str:
    """Compact millimetre text for a stock diameter (HUD)."""
    v = float(diameter_mm)
    rounded = round(v)
    if abs(v - rounded) < 0.05:
        return f"{int(rounded)}"
    return f"{v:.1f}"


def normalize_checkpoint_level(value: Any) -> str:
    """Return a known checkpoint-retention level, defaulting to ``medium``."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in CHECKPOINT_SLOTS_BY_LEVEL:
            return key
    return DEFAULT_CHECKPOINT_LEVEL


def checkpoint_slots_for_level(level: Any) -> int:
    """Slot count for a retention level (after normalization)."""
    return CHECKPOINT_SLOTS_BY_LEVEL[normalize_checkpoint_level(level)]
