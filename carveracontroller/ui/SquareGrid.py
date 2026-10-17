"""Jog-pad layout: pack children into equal squares, centered as a group.

The control page, the probing popup, and the CMM workbench place jog keys in
this grid so a wide or tall pad still yields square keys.
"""

from kivy.properties import NumericProperty
from kivy.uix.floatlayout import FloatLayout


class SquareGrid(FloatLayout):
    """Center a ``cols`` × ``rows`` block of equal squares inside the widget."""

    cols = NumericProperty(1)
    rows = NumericProperty(1)
    spacing = NumericProperty(0)
    padding = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fbind("cols", self._trigger_layout)
        self.fbind("rows", self._trigger_layout)
        self.fbind("spacing", self._trigger_layout)
        self.fbind("padding", self._trigger_layout)

    def do_layout(self, *args):
        # Kv declaration order is the reverse of Widget.children.
        ordered = list(reversed(self.children))
        cols = max(int(self.cols), 1)
        rows = max(int(self.rows), 1)
        spacing = float(self.spacing)
        pad = float(self.padding)
        slots = cols * rows
        # Size from the longer axis so a 2×3 pad matches the 3×3 pad beside it.
        span = max(cols, rows)
        avail_w = self.width - pad * 2 - spacing * (span - 1)
        avail_h = self.height - pad * 2 - spacing * (span - 1)
        side = min(avail_w / span, avail_h / span)
        side = max(side, 0.0)
        grid_w = side * cols + spacing * (cols - 1)
        grid_h = side * rows + spacing * (rows - 1)
        origin_x = self.x + (self.width - grid_w) / 2.0
        origin_y = self.y + (self.height - grid_h) / 2.0
        step = side + spacing
        for index, child in enumerate(ordered):
            if index >= slots:
                child.size_hint_x = None
                child.size_hint_y = None
                child.size = (0, 0)
                child.pos = (origin_x, origin_y)
                continue
            col = index % cols
            row = index // cols
            child.size_hint_x = None
            child.size_hint_y = None
            child.size = (side, side)
            child.pos = (
                origin_x + col * step,
                origin_y + (rows - 1 - row) * step,
            )
