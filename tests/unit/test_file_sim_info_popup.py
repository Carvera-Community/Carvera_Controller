"""File info popup builds its chart and fills the stat labels."""

from pathlib import Path

import numpy as np
from kivy.app import App
from kivy.base import EventLoop
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.widget import Widget

from carveracontroller.ui.file_sim_info.FileSimInfoPopup import FileSimInfoPopup
from carveracontroller.ui.file_sim_info.summary import summarize_file_sim
from carveracontroller.ui.theme import Theme

_ROOT = Path(__file__).resolve().parents[2] / "carveracontroller"


class _PopupTestApp(App):
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


def test_popup_shows_summary_on_the_chart():
    app = App.get_running_app()
    if app is None:
        app = _PopupTestApp()
    _ensure_app_attr(app, "show_tooltips", BooleanProperty(True), True)
    _ensure_app_attr(app, "tooltip_delay", NumericProperty(0), 0)
    _ensure_app_attr(app, "theme", ObjectProperty(None, rebind=True), Theme())
    if app.theme is None:
        app.theme = Theme()
    path = str(_ROOT / "ui/file_sim_info/FileSimInfoPopup.kv")
    if path not in Builder.files:
        Builder.load_file(path)
    EventLoop.ensure_window()

    popup = FileSimInfoPopup()
    summary = summarize_file_sim(
        filename="pocket.nc",
        positions=[0.0, 0.0, 0.0, 10.0, 0.0, 0.0, 20.0, 0.0, 0.0],
        mrr=np.array([0.0, 30.0, 12.0]),
        line_times=[0.0, 60.0, 120.0],
        vertex_types=[1.0, 1.0, 1.0],
        tools=[2, 2, 5],
    )
    popup._apply_summary(summary)

    assert popup.show_empty is False
    assert popup.file_text == "pocket.nc"
    assert popup.peak_text.endswith("mm³/min")
    assert "30" in popup.peak_text
    assert popup.coverage_text
    assert not hasattr(popup, "bounds_text")
    assert not hasattr(popup, "tools_text")
    labels = [line.get_label() for line, tool in popup._plotted if tool is not None]
    assert labels == ["T2", "T5"]
    colors = [tuple(line.get_color()) for line, tool in popup._plotted if tool is not None]
    assert colors[0] != colors[1]
    assert float(np.nanmax(popup._plotted[0][0].get_ydata())) == 30.0
