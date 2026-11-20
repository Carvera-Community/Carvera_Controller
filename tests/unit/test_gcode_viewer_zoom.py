"""Mouse-wheel zoom direction follows the gcode_zoom_revert setting."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from carveracontroller.GcodeViewer import GCodeViewer


def _viewer() -> GCodeViewer:
    viewer = GCodeViewer.__new__(GCodeViewer)
    viewer.collide_point = lambda *_: True
    viewer._handle_view_cube_touch = lambda _touch: False
    viewer.m_xRot = viewer.m_yRot = viewer.m_xPan = viewer.m_yPan = 0.0
    viewer.zoom_in = MagicMock()
    viewer.zoom_out = MagicMock()
    viewer.update_proj = MagicMock()
    viewer.update_view = MagicMock()
    return viewer


def _scroll(button):
    return SimpleNamespace(
        pos=(50, 50),
        ud={},
        profile=["button"],
        button=button,
        is_mouse_scrolling=True,
        is_double_tap=False,
    )


@pytest.mark.parametrize(
    ("revert", "button", "expected"),
    [
        (False, "scrollup", "zoom_in"),
        (False, "scrolldown", "zoom_out"),
        (True, "scrollup", "zoom_out"),
        (True, "scrolldown", "zoom_in"),
    ],
)
def test_mouse_wheel_zoom_direction(revert, button, expected):
    viewer = _viewer()

    with patch("carveracontroller.GcodeViewer.Config.getboolean", return_value=revert):
        viewer.on_touch_down(_scroll(button))

    getattr(viewer, expected).assert_called_once_with()
    other = "zoom_out" if expected == "zoom_in" else "zoom_in"
    getattr(viewer, other).assert_not_called()
