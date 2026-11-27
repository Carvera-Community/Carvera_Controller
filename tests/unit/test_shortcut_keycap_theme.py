"""Shortcut keycaps must drop their theme watch when the chord display rebuilds them."""

import gc
import weakref

import pytest
from kivy.app import App
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from carveracontroller.addons.keyboard_shortcuts.bindings import KeyChord
from carveracontroller.addons.keyboard_shortcuts.ui import _KeyCap, _ShortcutChordDisplay
from carveracontroller.ui.theme import Theme


class _ThemeApp(App):
    theme = ObjectProperty(None, allownone=True)
    show_tooltips = BooleanProperty(False)
    tooltip_delay = NumericProperty(0)

    def load_kv(self, filename=None):
        return False

    def build(self):
        return Widget()


@pytest.fixture
def themed_app():
    app = App.get_running_app() or _ThemeApp()
    original_theme = getattr(app, "theme", None)
    app.theme = Theme()
    yield app
    app.theme = original_theme


def test_clearing_keycaps_stops_theme_watch_and_new_ones_follow(themed_app):
    display = _ShortcutChordDisplay(KeyChord("k", ("ctrl",)))
    old_caps = list(display._keycaps)
    assert old_caps
    assert all(cap._stop_theme is not None for cap in old_caps)
    # Check the canvas colors rather than ``color``: when the app's kv is loaded, the global
    # ``<Label>`` rule re-themes ``color`` on every live label, detached or not. Only the
    # keycap's own theme watch updates the background and outline.
    stale_canvas = [(list(cap._bg_color.rgba), list(cap._outline_color.rgba)) for cap in old_caps]

    display.set_chord(KeyChord("m"))
    assert all(cap.parent is None for cap in old_caps)
    assert all(cap._stop_theme is None for cap in old_caps)

    new_text = [0.2, 0.4, 0.6, 1]
    new_inset = [0.1, 0.3, 0.5, 1]
    new_border = [0.7, 0.8, 0.9, 1]
    themed_app.theme.text = new_text
    themed_app.theme.panel_inset = new_inset
    themed_app.theme.border = new_border
    for cap, (bg, outline) in zip(old_caps, stale_canvas, strict=True):
        assert list(cap._bg_color.rgba) == pytest.approx(bg)
        assert list(cap._outline_color.rgba) == pytest.approx(outline)
    assert display._keycaps
    for cap in display._keycaps:
        assert list(cap.color) == pytest.approx(new_text)
        assert list(cap._bg_color.rgba) == pytest.approx(new_inset)
        assert list(cap._outline_color.rgba) == pytest.approx(new_border)


def test_removed_keycaps_are_not_kept_by_theme(themed_app):
    bar = BoxLayout()
    refs = []
    for label in ("Ctrl", "K"):
        cap = _KeyCap(text=label)
        refs.append(weakref.ref(cap))
        bar.add_widget(cap)
    del cap
    bar.clear_widgets()
    gc.collect()
    assert [ref() for ref in refs] == [None, None]

    display = _ShortcutChordDisplay(KeyChord("j"))
    created = weakref.ref(display._keycaps[0])
    display.set_chord(None)
    gc.collect()
    assert created() is None
