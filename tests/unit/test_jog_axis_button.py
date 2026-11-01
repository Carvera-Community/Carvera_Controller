"""Jog keys color the axis letter, the sign, or the key face while the key can be pressed."""

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


def test_jog_key_follows_the_axis_color_and_drops_it_when_disabled():
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
    previous = (
        bool(app.theme.jog_pad_axis_colors),
        bool(app.theme.jog_pad_sign_colors),
        bool(app.theme.jog_pad_axis_background),
    )
    app.theme.jog_pad_sign_colors = False
    app.theme.jog_pad_axis_background = False
    button = JogAxisButton(axis_label="X+")
    try:
        assert button.text == "X+"
        assert button.markup is False

        app.theme.jog_pad_axis_colors = True
        text, markup = jog_axis_markup(button.axis_label, app.theme)
        assert button.text == text
        assert button.markup is markup

        pad = FloatLayout()
        pad.add_widget(button)
        pad.disabled = True
        assert button.text == "X+"
        assert button.markup is False
        pad.disabled = False
        assert button.text == text
        assert button.markup is markup

        button.axis_label = "A-"
        text, markup = jog_axis_markup("A-", app.theme)
        assert button.text == text
        assert button.markup is markup

        app.theme.jog_pad_axis_colors = False
        app.theme.jog_pad_sign_colors = True
        text, markup = jog_axis_markup("A-", app.theme)
        assert button.text == text == f"A[color={_hex(app.theme.axis_a)}]-[/color]"
        assert button.markup is markup is True

        app.theme.jog_pad_axis_colors = True
        app.theme.jog_pad_axis_background = True
        assert button.text == "A-"
        assert button.markup is False

        app.theme.jog_pad_axis_colors = False
        app.theme.jog_pad_sign_colors = False
        app.theme.jog_pad_axis_background = False
        assert button.text == "A-"
        assert button.markup is False
    finally:
        app.theme.jog_pad_axis_colors, app.theme.jog_pad_sign_colors, app.theme.jog_pad_axis_background = previous
        if created:
            app.dispatch("on_stop")
            App._running_app = None


def _hex(color) -> str:
    from carveracontroller.ui.themes import format_hex_color

    return format_hex_color(color)


def test_jog_key_face_follows_the_axis_color():
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
    previous = bool(app.theme.jog_pad_axis_background)
    button = JogAxisButton(axis_label="X+", size_hint=(None, None), size=(80, 80))
    try:
        assert list(button.theme_fill) == pytest.approx(list(app.theme.control))
        app.theme.jog_pad_axis_background = True
        Builder.sync()
        assert list(button.theme_fill) == pytest.approx(list(app.theme.axis_x))
        assert list(button.color) == pytest.approx(app.theme.jog_axis_text("X+", "normal", False, True))
        button.state = "down"
        Builder.sync()
        assert list(button.theme_fill) == pytest.approx(app.theme.jog_axis_fill("X+", "down", False, True))
        button.disabled = True
        Builder.sync()
        assert list(button.theme_fill) == pytest.approx(list(app.theme.control_disabled))
    finally:
        app.theme.jog_pad_axis_background = previous
        if created:
            app.dispatch("on_stop")
            App._running_app = None
