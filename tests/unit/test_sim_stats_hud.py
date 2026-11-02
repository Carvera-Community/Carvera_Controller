"""Simulation HUD width tracks the stats text in both directions."""

from pathlib import Path

import pytest
from kivy.app import App
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.widget import Widget

from carveracontroller.GcodeViewer import SIM_VIEW_PATHS, SIM_VIEW_SIMULATION, SIM_VIEW_STOCK
from carveracontroller.ui.SimStatsHud import SimStatsHud, SimStatsHudIcon, SimViewMenuButton
from carveracontroller.ui.theme import Theme

SHORT = "Heightmap: 40x30\nResolution: 0.5mm/cell\nCheckpoints: 0% - 1/8 slots"
LONG = "Cylindrical: 400x180\nResolution: 0.25 mm along the X axis and at Ø40\nCheckpoints: 12% - 3/8 slots"

_ROOT = Path(__file__).resolve().parents[2] / "carveracontroller"


class _HudTestApp(App):
    show_gcode_ctl_bar = BooleanProperty(True)
    show_tooltips = BooleanProperty(True)
    tooltip_delay = NumericProperty(0)
    theme = ObjectProperty(None, rebind=True)

    def load_kv(self, filename=None):
        return False

    def build(self):
        return Widget()


def _ensure_app_attr(app, name, prop, value):
    if hasattr(app, name):
        return
    app.apply_property(**{name: prop})
    setattr(app, name, value)


@pytest.fixture
def sim_hud_kv():
    app = App.get_running_app()
    if app is None:
        app = _HudTestApp()
    _ensure_app_attr(app, "show_gcode_ctl_bar", BooleanProperty(True), True)
    _ensure_app_attr(app, "show_tooltips", BooleanProperty(True), True)
    _ensure_app_attr(app, "tooltip_delay", NumericProperty(0), 0)
    _ensure_app_attr(app, "theme", ObjectProperty(None, rebind=True), Theme())
    if app.theme is None:
        app.theme = Theme()
    for rel in ("addons/tooltips/Tooltips.kv", "ui/SimStatsHud.kv"):
        path = str(_ROOT / rel)
        if path not in Builder.files:
            Builder.load_file(path)
    EventLoop.ensure_window()
    return app


def _settle():
    for _ in range(12):
        EventLoop.idle()


def test_hud_width_unchanged_when_carving_toggles(sim_hud_kv):
    hud = SimStatsHud(hud_visible=True, stats_text=SHORT)
    Window.add_widget(hud)
    try:
        _settle()
        idle_width = hud.width
        assert idle_width > 0

        hud.carving = True
        _settle()
        assert hud.width == pytest.approx(idle_width, abs=1)

        hud.stats_text = LONG
        _settle()
        long_width = hud.width
        hud.carving = False
        _settle()
        assert hud.width == pytest.approx(long_width, abs=1)
    finally:
        Window.remove_widget(hud)


def test_hud_width_shrinks_when_stats_text_shortens(sim_hud_kv):
    hud = SimStatsHud(hud_visible=True, stats_text=SHORT)
    Window.add_widget(hud)
    try:
        _settle()
        short_width = hud.width
        assert short_width > 0

        hud.stats_text = LONG
        _settle()
        long_width = hud.width
        assert long_width > short_width + 20

        hud.stats_text = SHORT
        _settle()
        assert hud.width == pytest.approx(short_width, abs=1)
        assert hud.width < long_width - 20
    finally:
        Window.remove_widget(hud)


def test_hud_has_stock_settings_cog_next_to_eye(sim_hud_kv):
    hud = SimStatsHud(hud_visible=True, stats_text=SHORT)
    Window.add_widget(hud)
    try:
        _settle()
        icons = [w for w in hud.walk() if isinstance(w, SimStatsHudIcon)]
        sources = [w.icon_source for w in icons]
        assert any(source.endswith("cog.png") for source in sources)
        assert any(source.endswith("eye.png") for source in sources)
        cog = next(widget for widget in icons if widget.icon_source.endswith("cog.png"))
        assert "stock" in cog.tooltip_txt.lower()
        info = next(widget for widget in icons if widget.icon_source.endswith("information-outline.png"))
        assert "file" in info.tooltip_txt.lower()
        eye = next(widget for widget in icons if widget.icon_source.endswith("eye.png"))
        assert "simulation view" in eye.tooltip_txt.lower()
        assert eye.icon_active is True

        buttons = [widget for widget in hud._view_dropdown.walk() if isinstance(widget, SimViewMenuButton)]
        labels = [button.text.lower() for button in buttons]
        assert any("path" in label for label in labels)
        assert any(label == "stock" for label in labels)
        assert any(label == "simulation" for label in labels)
        assert hud._view_dropdown.view_mode == SIM_VIEW_SIMULATION
        assert next(button for button in buttons if button.text.lower() == "simulation").active is True

        hud.view_mode = SIM_VIEW_PATHS
        assert hud._view_dropdown.view_mode == SIM_VIEW_PATHS
        assert eye.icon_active is False
        assert next(button for button in buttons if "path" in button.text.lower()).active is True
        assert next(button for button in buttons if button.text.lower() == "stock").active is False

        hud.view_mode = SIM_VIEW_STOCK
        assert eye.icon_active is False
        assert next(button for button in buttons if button.text.lower() == "stock").active is True
    finally:
        Window.remove_widget(hud)


def test_view_menu_choice_sets_viewer_mode(sim_hud_kv):
    class _Viewer:
        def __init__(self):
            self.mode = None

        def set_sim_view(self, mode):
            self.mode = mode

    viewer = _Viewer()

    class _Root:
        def __init__(self):
            self.gcode_viewer = viewer

    previous_root = sim_hud_kv.root
    sim_hud_kv.root = _Root()
    hud = SimStatsHud(hud_visible=True, stats_text=SHORT)
    try:
        hud._view_dropdown._choose(SIM_VIEW_PATHS)
        assert viewer.mode == SIM_VIEW_PATHS
    finally:
        sim_hud_kv.root = previous_root
