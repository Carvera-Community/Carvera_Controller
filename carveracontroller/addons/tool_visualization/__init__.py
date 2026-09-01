"""Tool metadata extraction and 3D mesh generation for the G-code viewer.

This package generates 3D meshes and legend icons for tools described by CAM
header comments (parsed by ``carveracontroller.addons.cam``).
"""

from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType
from carveracontroller.addons.tool_visualization.tooltip_builder import format_tool_tooltip

__all__ = [
    "format_tool_tooltip",
    "ToolDefinition",
    "ToolType",
]
