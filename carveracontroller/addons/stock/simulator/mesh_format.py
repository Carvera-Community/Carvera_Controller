"""GPU vertex layout shared by every carved-stock mesh."""

from __future__ import annotations

# Same layout as tool meshes: pos(3) + normal(3) + color(4) + tc(2)
VERTEX_FORMAT = [
    (b"v_pos", 3, "float"),
    (b"v_normal", 3, "float"),
    (b"v_color", 4, "float"),
    (b"v_tc0", 2, "float"),
]

DEFAULT_COLOR = (0.75, 0.72, 0.55, 1.0)
