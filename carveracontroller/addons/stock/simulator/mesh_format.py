"""GPU vertex layout shared by every carved-stock mesh."""

from __future__ import annotations

from carveracontroller.ui.theme import get_theme

# Same layout as tool meshes: pos(3) + normal(3) + color(4) + tc(2)
VERTEX_FORMAT = [
    (b"v_pos", 3, "float"),
    (b"v_normal", 3, "float"),
    (b"v_color", 4, "float"),
    (b"v_tc0", 2, "float"),
]


def default_stock_color() -> tuple:
    """Default carved-stock color from the current theme."""
    return tuple(get_theme().viewer_stock_default)
