"""Recommend a stock carver backend from 3/4-axis, wrapping vs index, and tool profiles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from carveracontroller.addons.tool_visualization.mesh_builder import (
    effective_tool_diameter,
    fallback_tool_dimensions,
    profile_length,
    resolve_section_lengths,
    tool_profile,
)
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType

# Backends the worker can run.
BACKEND_HEIGHTMAP = "heightmap"
BACKEND_CYLINDRICAL = "cylindrical"
BACKEND_VOXEL = "voxel"

# User / settings modes (``auto`` resolves to one of the backends).
MODE_AUTO = "auto"
MODE_HEIGHTMAP = BACKEND_HEIGHTMAP
MODE_CYLINDRICAL = BACKEND_CYLINDRICAL
MODE_VOXEL = BACKEND_VOXEL

DEFAULT_CARVER_MODE = MODE_AUTO

KNOWN_CARVER_MODES = frozenset({MODE_AUTO, MODE_HEIGHTMAP, MODE_CYLINDRICAL, MODE_VOXEL})
KNOWN_BACKENDS = frozenset({BACKEND_HEIGHTMAP, BACKEND_CYLINDRICAL, BACKEND_VOXEL})

# Radius drop that counts as an undercut. Dexels cannot store re-entrant
# profiles at any resolution, so this is independent of cell size.
UNDERCUT_TOL_MM = 0.05


@dataclass(frozen=True)
class CarverRecommendation:
    """Resolved carver choice for the loaded file / tools / mode."""

    backend: str
    accuracy_tradeoff: bool
    allowed: frozenset[str]
    recommended: str
    has_4axis: bool
    has_undercut: bool
    has_off_axis_y: bool


def normalize_carver_mode(value: Any) -> str:
    """Return a known carver mode, defaulting to ``auto``."""
    if isinstance(value, str):
        key = value.strip().lower()
        if key in KNOWN_CARVER_MODES:
            return key
    return DEFAULT_CARVER_MODE


def _truncate_profile_to_cut(profile: list[tuple[float, float]], cut_z: float) -> list[tuple[float, float]]:
    if not profile or cut_z <= 0:
        return profile
    out: list[tuple[float, float]] = []
    for z, r in profile:
        if z <= cut_z + 1e-9:
            out.append((z, r))
        else:
            break
    if not out:
        return profile[:2] if len(profile) >= 2 else profile
    if out[-1][0] < cut_z - 1e-9:
        out.append((cut_z, out[-1][1]))
    return out


def resolve_cutting_profile(
    tool_def: ToolDefinition | None,
    tool_unit_scale: float = 1.0,
) -> list[tuple[float, float]]:
    """Cutting profile in mm (flute/shoulder only) — same rules as the voxel carver."""
    if tool_def is None:
        diameter, length = fallback_tool_dimensions(1.0)
        return [(0.0, diameter / 2.0), (length, diameter / 2.0)]

    profile = list(tool_profile(tool_def, scale=1.0))
    diameter = effective_tool_diameter(tool_def, scale=1.0)
    fallback_overall = profile_length(tool_def, scale=1.0, diameter=diameter)
    flute_z, shoulder_z, _overall = resolve_section_lengths(tool_def, fallback_overall)
    cut_z = max(flute_z, shoulder_z)
    profile = _truncate_profile_to_cut(profile, cut_z)
    s = float(tool_unit_scale) if tool_unit_scale else 1.0
    if s != 1.0:
        profile = [(z * s, r * s) for z, r in profile]
    return profile


def profile_undercuts(
    profile: Sequence[tuple[float, float]],
    tol_mm: float = UNDERCUT_TOL_MM,
) -> bool:
    """True if the cutting silhouette is re-entrant (wider below a narrower neck)."""
    if not profile:
        return False
    tol = max(float(tol_mm), 1e-9)
    peak = 0.0
    for _z, r in profile:
        rr = float(r)
        if peak - rr >= tol - 1e-12:
            return True
        peak = max(peak, rr)
    return False


def tool_table_has_undercut(tool_table: dict | None, tool_unit_scale: float = 1.0) -> bool:
    """True if any tool in the table has a re-entrant cutting profile (excl. thread mills)."""
    if not tool_table:
        return False
    for tool_def in tool_table.values():
        if getattr(tool_def, "tool_type", None) is ToolType.THREAD_MILL:
            continue
        profile = resolve_cutting_profile(tool_def, tool_unit_scale=tool_unit_scale)
        if profile_undercuts(profile):
            return True
    return False


def _allowed_backends(has_4axis: bool) -> frozenset[str]:
    if has_4axis:
        # Rotary: cylindrical (outside-in) or voxels — never Z-heightmap.
        return frozenset({BACKEND_CYLINDRICAL, BACKEND_VOXEL})
    return frozenset({BACKEND_HEIGHTMAP, BACKEND_VOXEL})


def _auto_backend(has_4axis: bool, has_undercut: bool, has_off_axis_y: bool = False) -> str:
    if has_undercut:
        return BACKEND_VOXEL
    if has_4axis:
        return BACKEND_VOXEL if has_off_axis_y else BACKEND_CYLINDRICAL
    return BACKEND_HEIGHTMAP


def recommend_carver(
    *,
    mode: str = MODE_AUTO,
    has_4axis: bool = False,
    has_off_axis_y: bool = False,
    tool_table: dict | None = None,
    tool_unit_scale: float = 1.0,
) -> CarverRecommendation:
    """Pick backend + allowed overrides from 4-axis, wrapping vs index, and tools."""
    mode = normalize_carver_mode(mode)
    rotary = bool(has_4axis)
    off_axis = bool(has_off_axis_y)
    has_undercut = tool_table_has_undercut(tool_table, tool_unit_scale)
    allowed = _allowed_backends(rotary)
    recommended = _auto_backend(rotary, has_undercut, off_axis)

    if mode == MODE_AUTO:
        backend = recommended
    elif mode in allowed:
        backend = mode
    else:
        # Wrong family (e.g. heightmap on a 4-axis file): fall back.
        backend = recommended

    accuracy_tradeoff = bool(has_undercut and backend != BACKEND_VOXEL)

    return CarverRecommendation(
        backend=backend,
        accuracy_tradeoff=accuracy_tradeoff,
        allowed=allowed,
        recommended=recommended,
        has_4axis=rotary,
        has_undercut=has_undercut,
        has_off_axis_y=off_axis,
    )
