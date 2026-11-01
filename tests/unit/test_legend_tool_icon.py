"""Colored tool previews stay colored on a light theme.

The legend image multiplies its texture by ``color``. Label text is nearly
black in the light palette, so using it as that tint turns the gold flute
into a silhouette. The tooltip does not tint, which is why it stayed correct.
"""

from contextlib import contextmanager
from pathlib import Path

from kivy.app import App
from kivy.base import EventLoop
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty

from carveracontroller.addons.tool_visualization import ToolDefinition, ToolType
from carveracontroller.ui.GcodeColorSchemePanel import LegendRow, SchemeSpinner
from carveracontroller.ui.theme import Theme


class _LegendApp(App):
    theme = ObjectProperty(None, rebind=True)
    show_tooltips = BooleanProperty(False)
    tooltip_delay = NumericProperty(0)
    tool = NumericProperty(1)

    def load_kv(self, filename=None):
        return False

    def build(self):
        return None


@contextmanager
def _app():
    app = App.get_running_app() or _LegendApp()
    if "theme" not in app.properties():
        app.apply_property(theme=ObjectProperty(None, rebind=True))
    if "tooltip_delay" not in app.properties():
        app.apply_property(tooltip_delay=NumericProperty(0))
    if "show_tooltips" not in app.properties():
        app.apply_property(show_tooltips=BooleanProperty(False))
    # The suite shares one Kivy app. Put the light palette back when the test ends.
    previous = app.theme
    app.theme = Theme("light")
    root = Path(__file__).resolve().parents[2] / "carveracontroller"
    for rel in ("ui/theme.kv", "addons/tooltips/Tooltips.kv", "ui/GcodeColorSchemePanel.kv"):
        path = str(root / rel)
        if path not in Builder.files:
            Builder.load_file(path)
    EventLoop.ensure_window()
    try:
        yield app
    finally:
        app.theme = previous


def _mill_row():
    tool_def = ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=3.175,
        length=12.0,
        description="3.175mm flat end mill",
    )
    return LegendRow(
        {
            "label": "T1",
            "color": (0.4, 0.7, 0.2, 1),
            "key": 1,
            "kind": "tool",
            "tool_def": tool_def,
        },
        visible=True,
        is_active_tool=False,
        active_color=(0.2, 0.6, 0.9, 1),
        on_toggle=lambda *_args: None,
        show_icon_column=True,
    )


def test_legend_preview_keeps_its_colors_on_a_light_theme():
    with _app() as app:
        row = _mill_row()
        assert row._icon is not None
        assert row._icon_monochrome is False
        assert list(row._icon.color) == [1, 1, 1, 1]
        assert row._icon.opacity == 1
        # The light label color is what used to paint the silhouette.
        assert list(row._icon.color) != list(app.theme.text)

        row.visible = False
        assert list(row._icon.color) == [1, 1, 1, 1]
        assert row._icon.opacity < 1

        row.visible = True
        assert row._icon.opacity == 1


def test_scheme_menu_is_wide_enough_for_its_longest_label():
    with _app():
        spinner = SchemeSpinner(
            option_cls="SchemeSpinnerOption",
            text="Tool",
            values=["Tool", "Move type", "Speed", "Height"],
            size_hint=(None, None),
            size=(dp(52), dp(28)),
        )
        dropdown = spinner._dropdown
        assert dropdown.auto_width is False
        assert dropdown.width > spinner.width + dp(40)
        move = next(child for child in dropdown.container.children if child.text == "Move type")
        assert move.height == dp(40)
        assert move.shorten is True
        assert move.text_size[0] == move.width - dp(16)


def test_monochrome_legend_glyph_still_follows_the_label_color():
    with _app() as app:
        row = LegendRow(
            {
                "label": "Probe",
                "color": (0.9, 0.2, 0.2, 1),
                "key": 0,
                "kind": "tool",
                "tool": 0,
            },
            visible=True,
            is_active_tool=False,
            active_color=(0.2, 0.6, 0.9, 1),
            on_toggle=lambda *_args: None,
            show_icon_column=True,
        )
        assert row._icon_monochrome is True
        assert list(row._icon.color) == list(app.theme.text)
