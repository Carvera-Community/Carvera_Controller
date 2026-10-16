"""Jog keys color the axis letter only while the key can be pressed."""

from kivy.app import App
from kivy.properties import ObjectProperty
from kivy.uix.floatlayout import FloatLayout

from carveracontroller.ui.JogAxisButton import JogAxisButton
from carveracontroller.ui.theme import Theme
from carveracontroller.ui.themes import jog_axis_markup


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
    previous = bool(app.theme.jog_pad_axis_colors)
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
        assert button.text == "A-"
        assert button.markup is False
    finally:
        app.theme.jog_pad_axis_colors = previous
        if created:
            app.dispatch("on_stop")
            App._running_app = None
