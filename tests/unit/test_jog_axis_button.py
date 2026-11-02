"""Jog keys use custom letter, sign, and face colors while the key can be pressed."""

from pathlib import Path

import pytest
from kivy.app import App
from kivy.lang import Builder
from kivy.properties import ObjectProperty
from kivy.uix.floatlayout import FloatLayout

from carveracontroller.ui.JogAxisButton import JogAxisButton
from carveracontroller.ui.theme import Theme
from carveracontroller.ui.themes import jog_axis_markup

_THEME_KV = Path(__file__).resolve().parents[2] / "carveracontroller" / "ui" / "theme.kv"


def test_jog_key_follows_custom_colors_and_drops_them_when_disabled():
    created = App.get_running_app() is None
    app = App.get_running_app()
    if created:

        class _JogThemeApp(App):
            theme = ObjectProperty(None, rebind=True)

            def build(self):
                return None

        app = _JogThemeApp()
    if "theme" not in app.properties():
        app.apply_property(theme=ObjectProperty(None, rebind=True))
    if app.theme is None:
        app.theme = Theme()
    previous = bool(app.theme.jogging_custom_colors)
    app.theme.jogging_custom_colors = False
    button = JogAxisButton(axis_label="X+")
    try:
        assert button.text == "X+"
        assert button.markup is False

        app.theme.jogging_custom_colors = True
        text, markup = jog_axis_markup(button.axis_label, app.theme, button.state)
        assert button.text == text
        assert button.markup is markup is True

        pad = FloatLayout()
        pad.add_widget(button)
        pad.disabled = True
        assert button.text == "X+"
        assert button.markup is False
        pad.disabled = False
        assert button.text == text
        assert button.markup is markup

        button.axis_label = "A-"
        text, markup = jog_axis_markup("A-", app.theme, "normal")
        assert button.text == text
        assert button.markup is markup

        button.state = "down"
        down_text, down_markup = jog_axis_markup("A-", app.theme, "down")
        assert down_text != text
        assert button.text == down_text
        assert button.markup is down_markup is True

        app.theme.jogging_custom_colors = False
        assert button.text == "A-"
        assert button.markup is False
    finally:
        app.theme.jogging_custom_colors = previous
        if created:
            app.dispatch("on_stop")
            App._running_app = None


def test_jog_key_face_follows_custom_colors():
    created = App.get_running_app() is None
    app = App.get_running_app()
    if created:

        class _JogFaceApp(App):
            theme = ObjectProperty(None, rebind=True)

            def build(self):
                return None

        app = _JogFaceApp()
    if "theme" not in app.properties():
        app.apply_property(theme=ObjectProperty(None, rebind=True))
    if app.theme is None:
        app.theme = Theme()
    if not any(str(path).replace("\\", "/").endswith("ui/theme.kv") for path in Builder.files):
        Builder.load_file(str(_THEME_KV))
    previous = bool(app.theme.jogging_custom_colors)
    app.theme.jogging_custom_colors = False
    button = JogAxisButton(axis_label="X+", size_hint=(None, None), size=(80, 80))
    try:
        assert list(button.theme_fill) == pytest.approx(list(app.theme.control))
        app.theme.jogging_custom_colors = True
        Builder.sync()
        assert list(button.theme_fill) == pytest.approx(list(app.theme.jogging_x_background))
        assert list(button.color) == pytest.approx(app.theme.jog_axis_text("X+", "normal", False, True))
        assert button.text == jog_axis_markup("X+", app.theme, "normal")[0]
        button.state = "down"
        Builder.sync()
        assert list(button.theme_fill) == pytest.approx(app.theme.jog_axis_fill("X+", "down", False, True))
        assert button.text == jog_axis_markup("X+", app.theme, "down")[0]
        button.disabled = True
        Builder.sync()
        assert list(button.theme_fill) == pytest.approx(list(app.theme.control_disabled))
        assert button.text == "X+"
        assert button.markup is False
    finally:
        app.theme.jogging_custom_colors = previous
        if created:
            app.dispatch("on_stop")
            App._running_app = None
